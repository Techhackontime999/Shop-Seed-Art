"""Product/background segmentation.

Two interchangeable implementations behind one interface:

``ClassicalSegmenter``
    A deterministic computer-vision segmenter built on numpy + scipy. It
    models the background from the border of the frame, then keeps only the
    background-coloured regions that actually touch the border, so a
    similarly-coloured *detail inside* the product (a white highlight on a
    white pot, a pale border on a cream saree) is not mistaken for
    background. Runs everywhere with no extra dependency, is deterministic,
    and is fast enough for a synchronous request.

``U2NetSegmenter``
    Wraps the optional ``rembg`` package (u2net / isnet general segmentation
    models). Better on hair, embroidery and semi-transparent edges. It is a
    real extra dependency, so it is opt-in: if ``rembg`` is not installed the
    factory silently uses the classical one and the pipeline still works.

Both return a grayscale mask where 255 is product and 0 is background, and
both may return ``None`` to say "I could not isolate this product" — which
the pipeline treats as a signal to keep the seller's own background rather
than to guess.
"""

import logging
from abc import ABC, abstractmethod
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Segmentation runs on a downscaled copy; 720px is where the silhouette of a
# product is fully resolved and the cost is still a few milliseconds.
_SEGMENT_EDGE = 720

# Plausibility bounds for "fraction of the frame that is product". Below the
# floor we have almost certainly grabbed a shadow; above the ceiling we have
# not removed anything.
_MIN_FOREGROUND = 0.02
_MAX_FOREGROUND = 0.97

# Edge feathering, in working pixels. Textile and fibre edges need a soft
# alpha or the cut-out looks scissored.
_FEATHER_RADIUS = 1.1

# Luma-weighted RGB distance weights (classic YIQ/Rec.601 sensitivities).
_W = np.array([2.0, 4.0, 3.0], dtype=np.float32)


class Segmenter(ABC):
    name = 'base'

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def segment(self, image: Image.Image):
        """Return a product mask ('L' image, 255 = product) or ``None``."""


def _otsu(values: np.ndarray) -> float:
    """Otsu's threshold on a 1-D float array, computed from its histogram."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    lo, hi = float(finite.min()), float(finite.max())
    if hi - lo < 1e-6:
        return hi

    hist, edges = np.histogram(finite, bins=256, range=(lo, hi))
    total = hist.sum()
    if total == 0:
        return hi

    centres = (edges[:-1] + edges[1:]) / 2.0
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    sum_all = float((hist * centres).sum())
    sum_bg = np.cumsum(hist * centres)

    # Guard the divisions: an all-background or all-foreground split is
    # degenerate, and the 0/0 there would poison the variance product.
    valid = (weight_bg > 0) & (weight_fg > 0)
    if not valid.any():
        return hi

    mean_bg = np.zeros_like(centres, dtype=np.float64)
    mean_fg = np.zeros_like(centres, dtype=np.float64)
    mean_bg[valid] = sum_bg[valid] / weight_bg[valid]
    mean_fg[valid] = (sum_all - sum_bg[valid]) / weight_fg[valid]

    variance = np.zeros_like(centres, dtype=np.float64)
    variance[valid] = weight_bg[valid] * weight_fg[valid] * (mean_bg[valid] - mean_fg[valid]) ** 2
    return float(centres[int(np.argmax(variance))])


def _largest_component_touching(binary: np.ndarray, seed_fn) -> np.ndarray:
    """Keep the single largest True-component that satisfies ``seed_fn``."""
    from scipy import ndimage

    if not binary.any():
        return binary
    labels, count = ndimage.label(binary)
    if count == 0:
        return binary
    sizes = ndimage.sum(binary, labels, index=np.arange(1, count + 1))
    best, best_size = 0, 0.0
    for label_index in range(1, count + 1):
        if seed_fn(labels == label_index) and sizes[label_index - 1] > best_size:
            best, best_size = label_index, float(sizes[label_index - 1])
    if best == 0:
        # Nothing matched the seed; fall back to the biggest component so the
        # result is still a coherent object rather than scattered noise.
        best = int(np.argmax(sizes)) + 1
    return labels == best


def _touches_border(labels: np.ndarray, border: int) -> bool:
    return bool(
        labels[0, :].any() or labels[-1, :].any()
        or labels[:, 0].any() or labels[:, -1].any()
    )


def _contains_center(labels: np.ndarray) -> bool:
    h, w = labels.shape
    return bool(labels[h // 2, w // 2])


class ClassicalSegmenter(Segmenter):
    """Border-seeded colour segmentation with morphological cleanup."""

    name = 'classical'

    def is_available(self) -> bool:
        return True

    # -- public --------------------------------------------------------

    def segment(self, image: Image.Image):
        try:
            return self._segment(image)
        except Exception:
            # Segmentation is an enhancement, never a hard requirement. Any
            # internal failure degrades to "keep the original background".
            logger.exception('Classical segmentation failed; keeping original background')
            return None

    # -- internals -----------------------------------------------------

    def _segment(self, image: Image.Image):
        from scipy import ndimage

        rgb = image.convert('RGB')
        small = rgb.copy()
        small.thumbnail((_SEGMENT_EDGE, _SEGMENT_EDGE), Image.LANCZOS)
        h, w = small.size[1], small.size[0]
        if h < 8 or w < 8:
            return None

        arr = np.asarray(small, dtype=np.float32)
        # Colour distance from a robust background estimate.
        distance = self._distance_map(arr)

        # Otsu gives a good starting split; a small multiplier sweep lets us
        # cope with a product that happens to sit close to the background tone.
        base = max(_otsu(distance), 1e-3)
        for factor in (1.0, 0.75, 1.35, 0.55, 1.8):
            mask = self._mask_for_threshold(distance, base * factor)
            if mask is None:
                continue
            return self._finalise(mask, (w, h), image.size)
        return None

    def _distance_map(self, arr: np.ndarray) -> np.ndarray:
        """Per-pixel perceptual distance from the background colour model."""
        h, w, _ = arr.shape
        band = max(2, int(round(min(h, w) * 0.04)))

        # The background is whatever touches the frame, so estimate it from a
        # band along all four edges rather than a single corner (a product is
        # rarely centred in a seller's phone photo).
        strips = np.concatenate([
            arr[:band].reshape(-1, 3),
            arr[-band:].reshape(-1, 3),
            arr[:, :band].reshape(-1, 3),
            arr[:, -band:].reshape(-1, 3),
        ])
        background = np.median(strips, axis=0)

        diff = (arr - background[None, None, :]) * _W[None, None, :]
        return np.sqrt((diff * diff).sum(axis=2))

    def _mask_for_threshold(self, distance: np.ndarray, threshold: float):
        """Background = close to the model *and* connected to the frame."""
        from scipy import ndimage

        candidate = distance < threshold
        if not candidate.any() or candidate.all():
            return None

        # Keep only background blobs that reach the border. This is the step
        # that protects a white rim on a cream product from being deleted.
        labels, count = ndimage.label(candidate)
        if count == 0:
            return None
        sizes = ndimage.sum(candidate, labels, index=np.arange(1, count + 1))
        border_labels = set(np.unique(np.concatenate([
            labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
        ])))
        border_labels.discard(0)
        if not border_labels:
            return None

        keep = np.zeros(count + 1, dtype=bool)
        for label_index in border_labels:
            # Ignore a border blob that is nearly the whole frame: that is the
            # background only if the product is genuinely tiny, and the
            # plausibility check below catches the bad cases.
            keep[label_index] = True
        background_connected = keep[labels]

        foreground = ~background_connected
        fraction = float(foreground.mean())
        if not (_MIN_FOREGROUND <= fraction <= _MAX_FOREGROUND):
            return None

        # Close small gaps (weave showing the backdrop through), then keep the
        # dominant product component.
        foreground = ndimage.binary_closing(foreground, structure=np.ones((3, 3)), iterations=2)
        foreground = ndimage.binary_opening(foreground, structure=np.ones((3, 3)), iterations=1)
        foreground = _largest_component_touching(foreground, _contains_center)
        if not foreground.any():
            return None

        fraction = float(foreground.mean())
        if not (_MIN_FOREGROUND <= fraction <= _MAX_FOREGROUND):
            return None
        return foreground

    def _finalise(self, foreground: np.ndarray, small_size, full_size):
        """Clean, fill and feather, then return a full-resolution mask."""
        from scipy import ndimage

        # Holes inside the product (a dark spot, a cut-out handle) are product,
        # not background.
        foreground = ndimage.binary_fill_holes(foreground)

        alpha = Image.fromarray((foreground * 255).astype(np.uint8), mode='L')
        alpha = alpha.resize(full_size, Image.BILINEAR)
        # A one-pixel blur turns a jagged staircase edge into a usable alpha
        # ramp. Without it, embroidery and fibre edges alias badly.
        alpha = alpha.filter(ImageFilter.GaussianBlur(_FEATHER_RADIUS))
        return alpha


class U2NetSegmenter(Segmenter):
    """Neural segmentation via the optional ``rembg`` package.

    The model is loaded once per process and reused; ``rembg`` is called
    through a cached session so a burst of requests does not re-read the
    weights.
    """

    name = 'u2net'

    def __init__(self, model_name: str = 'u2net'):
        self.model_name = model_name
        self._session = None

    def is_available(self) -> bool:
        try:
            import rembg  # noqa: F401
        except ImportError:
            return False
        return True

    @lru_cache(maxsize=2)
    def _get_session(self, model_name: str):
        from rembg import new_session

        return new_session(model_name)

    def segment(self, image: Image.Image):
        if not self.is_available():
            return None
        try:
            from rembg import remove

            session = self._get_session(self.model_name)
            small = image.convert('RGB').copy()
            small.thumbnail((_SEGMENT_EDGE * 2, _SEGMENT_EDGE * 2), Image.LANCZOS)
            cut = remove(small, session=session)
            if cut.mode != 'RGBA':
                cut = cut.convert('RGBA')
            alpha = cut.split()[-1].resize(image.size, Image.BILINEAR)
            alpha = alpha.filter(ImageFilter.GaussianBlur(_FEATHER_RADIUS))
            # rembg can return an almost-empty alpha for images it does not
            # understand; treat that as "no segmentation" rather than
            # producing a blank product.
            if float(np.asarray(alpha, dtype=np.float32).mean()) < 6.0:
                return None
            return alpha
        except Exception:
            logger.exception('u2net segmentation failed; keeping original background')
            return None
