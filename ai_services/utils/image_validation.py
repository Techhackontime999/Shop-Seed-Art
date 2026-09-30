"""Untrusted-upload validation for the image enhancement pipeline.

Nothing here trusts the client. The declared ``Content-Type``, the file
extension and the filename are all attacker-controlled and are treated as
hints only; the verdict comes from the file's own bytes. A PHP script
renamed to ``photo.jpg`` and uploaded as ``image/jpeg`` is rejected because
Pillow cannot decode it, and it is rejected *before* it reaches any
provider or the filesystem.

Every failure raises :class:`ImageValidationError` carrying a short, safe
``code`` for the API and a plain-English ``message`` that is safe to show a
seller. Internal detail (offsets, magic numbers) stays in ``detail`` for the
server log.
"""

from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, UnidentifiedImageError

# Formats we can actually decode and re-encode. Anything else is refused
# rather than guessed at.
ALLOWED_FORMATS = {
    'JPEG': ('.jpg', '.jpeg'),
    'PNG': ('.png',),
    'WEBP': ('.webp',),
    'BMP': ('.bmp',),
    'TIFF': ('.tiff', '.tif'),
    'GIF': ('.gif',),
}

# Leading bytes, checked before handing anything to Pillow. This is a cheap
# first pass that catches renamed executables and archives without paying for
# a full decode.
_MAGIC = (
    (b'\xff\xd8\xff', 'JPEG'),
    (b'\x89PNG\r\n\x1a\n', 'PNG'),
    (b'RIFF', 'WEBP'),      # refined by the RIFF....WEBP form check below
    (b'BM', 'BMP'),
    (b'II*\x00', 'TIFF'),
    (b'MM\x00*', 'TIFF'),
    (b'GIF87a', 'GIF'),
    (b'GIF89a', 'GIF'),
)

# A format whose decoder is a known source of memory/CPU exhaustion. GIF in
# particular can declare a 64000x64000 canvas. We simply refuse it.
UNSUPPORTED_DECODERS = {'GIF'}


class ImageValidationError(Exception):
    """A rejected upload. Safe to surface to the seller."""

    def __init__(self, code: str, message: str, detail: str = ''):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass
class ValidatedImage:
    """The outcome of a successful validation pass."""

    format: str
    size: tuple
    mode: str
    width: int
    height: int
    filename: str
    byte_size: int
    animated: bool = False
    warnings: list = field(default_factory=list)


def sniff_format(head: bytes) -> Optional[str]:
    """Best-effort format guess from the first bytes of a file."""
    for magic, fmt in _MAGIC:
        if not head.startswith(magic):
            continue
        if fmt == 'WEBP':
            # 'RIFF' alone is any RIFF container; the WEBP form type is what
            # actually identifies the image.
            if len(head) < 12 or head[8:12] != b'WEBP':
                return None
        return fmt
    if head[:4] == b'<?xm' or head.lstrip()[:5] == b'<?xml':
        # SVG and other XML are the classic "image" that is really a document.
        return 'SVG_OR_XML'
    return None


def validate_upload(upload, *, max_bytes: int, max_pixels: int, min_edge: int = 64):
    """Validate an uploaded image without fully decoding it.

    Reads only the header, so a decompression-bomb style file is rejected on
    its declared dimensions before the pixels are ever allocated.
    """
    if upload is None:
        raise ImageValidationError(
            'missing_file', 'Please choose a photo of your product.'
        )

    size = getattr(upload, 'size', 0) or 0
    if size <= 0:
        raise ImageValidationError(
            'empty_file', 'That file is empty. Please choose another photo.'
        )
    if size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ImageValidationError(
            'file_too_large',
            'That photo is larger than %d MB. Please choose a smaller one.' % limit_mb,
            detail='uploaded %d bytes, limit %d' % (size, max_bytes),
        )

    try:
        head = upload.read(64)
    except Exception as exc:  # pragma: no cover - defensive
        raise ImageValidationError(
            'unreadable', 'That file could not be read. Please try again.'
        ) from exc
    finally:
        try:
            upload.seek(0)
        except Exception:  # pragma: no cover - some streams are not seekable
            pass

    sniffed = sniff_format(head)
    if sniffed is None:
        raise ImageValidationError(
            'not_an_image',
            "That doesn't look like a photo. Please choose a photo of your product.",
            detail='unrecognised magic bytes: %r' % head[:16],
        )
    if sniffed in UNSUPPORTED_DECODERS:
        raise ImageValidationError(
            'unsupported_format',
            'That image type is not supported. Please choose a JPG, PNG or WebP photo.',
            detail='decoder refused: %s' % sniffed,
        )

    try:
        with Image.open(upload) as img:
            fmt = (img.format or '').upper()
            width, height = img.size
            mode = img.mode
            animated = bool(getattr(img, 'is_animated', False))
            try:
                upload.seek(0)
            except Exception:  # pragma: no cover
                pass
    except UnidentifiedImageError as exc:
        raise ImageValidationError(
            'corrupt_image',
            'That photo appears to be damaged. Please choose another one.',
            detail='Pillow could not identify the file',
        ) from exc
    except Image.DecompressionBombError as exc:
        raise ImageValidationError(
            'image_too_large',
            'That photo has more detail than we can process. Please choose a smaller one.',
            detail='decompression bomb refused by Pillow',
        ) from exc
    except Exception as exc:
        # Pillow raises a wide variety of errors on malformed files; none of
        # them are actionable for the seller, so they collapse into one code.
        raise ImageValidationError(
            'corrupt_image',
            'That photo appears to be damaged. Please choose another one.',
            detail='%s: %s' % (type(exc).__name__, exc),
        ) from exc

    # The sniffed format is the stronger signal: a file whose extension and
    # declared type claim JPEG but whose bytes are PNG is fine, but a file
    # whose bytes are nothing like the sniff is not.
    if sniffed != 'SVG_OR_XML' and sniffed != fmt:
        raise ImageValidationError(
            'type_mismatch',
            'That file is not a valid photo. Please choose another one.',
            detail='sniffed %s, decoder reported %s' % (sniffed, fmt),
        )

    if fmt not in ALLOWED_FORMATS:
        raise ImageValidationError(
            'unsupported_format',
            'That image type is not supported. Please choose a JPG, PNG or WebP photo.',
            detail='format %s' % fmt,
        )

    if width < min_edge or height < min_edge:
        raise ImageValidationError(
            'image_too_small',
            'That photo is too small. Please choose one that is at least %d pixels on '
            'each side.' % min_edge,
            detail='%dx%d' % (width, height),
        )

    if width * height > max_pixels:
        raise ImageValidationError(
            'image_too_large',
            'That photo is too large to process. Please choose a smaller one.',
            detail='%d pixels, limit %d' % (width * height, max_pixels),
        )

    return ValidatedImage(
        format=fmt,
        size=(width, height),
        mode=mode,
        width=width,
        height=height,
        filename=getattr(upload, 'name', '') or 'photo',
        byte_size=size,
        animated=animated,
    )
