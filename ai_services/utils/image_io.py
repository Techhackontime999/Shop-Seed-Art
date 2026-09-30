"""Safe image loading, orientation handling and encoding helpers.

Everything that decodes a seller's photo goes through :func:`open_image` so
that a single set of rules applies everywhere: Pillow's decompression-bomb
guard is armed, the working copy is kept inside a bounded canvas, EXIF
orientation is applied to the pixels, and the metadata (including GPS and
camera serials) is dropped rather than carried into a published listing.
"""

import io
import os

from PIL import Image, ImageOps, UnidentifiedImageError

from .image_validation import ImageValidationError

# Metadata never leaves the pipeline: an artisan phone photo routinely
# carries GPS coordinates of their home and workshop.
_STRIP_EXIF = True

# Guard Pillow's own bomb protection at a level appropriate for a web upload.
# 0 disables it; the upper bound here is still well below anything we would
# ever want to allocate.
Image.MAX_IMAGE_PIXELS = 64_000_000


class ImageIOError(Exception):
    """An image could not be decoded or encoded."""


def open_image(source, *, max_edge: int = 0) -> Image.Image:
    """Decode ``source`` into a normalised, RGB-ready Pillow image.

    ``source`` may be a file object, raw bytes or a path. The returned image
    is a detached copy (no lazily-read file handle), with EXIF orientation
    baked into the pixels and all metadata stripped.
    """
    if isinstance(source, Image.Image):
        img = source.copy()
    else:
        try:
            if isinstance(source, bytes):
                handle = io.BytesIO(source)
            else:
                handle = source
            img = Image.open(handle)
            img.load()
        except Image.DecompressionBombError as exc:
            raise ImageIOError('decompression bomb refused') from exc
        except UnidentifiedImageError as exc:
            raise ImageIOError('unidentifiable image data') from exc
        except Exception as exc:
            raise ImageIOError('%s: %s' % (type(exc).__name__, exc)) from exc

    try:
        # Rotates the pixels to match EXIF so portraits are not sideways, and
        # handles the mirrored orientations some phones emit.
        img = ImageOps.exif_transpose(img) or img
    except Exception:
        # A malformed EXIF block must not cost us the image; the pixels are
        # still perfectly usable without it.
        pass

    if _STRIP_EXIF:
        try:
            img.info.pop('exif', None)
            img.info.pop('icc_profile', None)
        except Exception:  # pragma: no cover - defensive
            pass

    if max_edge:
        img = bound_image(img, max_edge)

    if img.mode in ('RGBA', 'LA', 'P'):
        # Keep alpha available for a transparent-background request; callers
        # flatten explicitly when they need an opaque canvas.
        img = img.convert('RGBA')
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    return img


def bound_image(img: Image.Image, max_edge: int) -> Image.Image:
    """Downscale so neither side exceeds ``max_edge``. Never upscales."""
    w, h = img.size
    longest = max(w, h)
    if longest <= max_edge:
        return img
    scale = max_edge / float(longest)
    size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return img.resize(size, Image.LANCZOS)


def encode_image(img: Image.Image, fmt: str = 'JPEG', quality: int = 90) -> bytes:
    """Encode to bytes, stripping metadata and applying sane encoder limits."""
    if fmt.upper() == 'JPEG':
        if img.mode not in ('RGB', 'L'):
            # JPEG has no alpha; flatten onto white rather than black so a
            # transparent product does not gain a dark halo.
            img = img.convert('RGBA')
            backdrop = Image.new('RGB', img.size, (255, 255, 255))
            backdrop.paste(img, mask=img.split()[-1])
            img = backdrop
        elif img.mode == 'L':
            img = img.convert('RGB')
        params = {
            'quality': quality,
            'optimize': True,
            'progressive': True,
            'subsampling': 0,   # 4:4:4 keeps embroidery and woven edges crisp
        }
    elif fmt.upper() == 'WEBP':
        params = {'quality': quality, 'method': 4}
    elif fmt.upper() == 'PNG':
        params = {'optimize': True, 'compress_level': 7}
    else:
        params = {}

    buffer = io.BytesIO()
    try:
        img.save(buffer, format=fmt, **params)
    except Exception as exc:
        raise ImageIOError('could not encode %s: %s' % (fmt, exc)) from exc
    return buffer.getvalue()


def safe_extension(fmt: str) -> str:
    from .image_validation import ALLOWED_FORMATS

    extensions = ALLOWED_FORMATS.get(fmt.upper())
    if not extensions:
        return '.jpg'
    return extensions[0]


def sanitise_filename(name: str, fallback: str = 'product') -> str:
    """Reduce an untrusted name to a safe stem.

    Strips directory components (so ``../../etc/passwd`` cannot survive) and
    anything outside ``[A-Za-z0-9_-]``. The result is never empty and never
    contains a leading dot, which also removes the chance of writing dotfiles.
    """
    name = os.path.basename(name or '')
    name = os.path.splitext(name)[0]
    cleaned = ''.join(ch for ch in name if ch.isalnum() or ch in '-_')
    cleaned = cleaned.strip('-_')
    if not cleaned:
        cleaned = fallback
    return cleaned[:60]
