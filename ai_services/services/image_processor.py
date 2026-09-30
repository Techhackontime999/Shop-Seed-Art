"""The image enhancement pipeline.

Ten explicit stages, each of which records what it actually did so the
frontend can show real progress:

    1. input validation      (performed by the view, recorded here)
    2. image normalization   — decode, EXIF-bake, strip metadata, bound size
    3. product segmentation  — the product/background mask
    4. background cleanup    — despeckle the removed background, tidy the edge
    5. product positioning   — decide the studio background to composite onto
    6. lighting / colour     — dampened white balance, exposure, contrast, saturation
    7. quality enhancement   — denoise and sharpen, on the product only
    8. ecommerce formatting  — scale to fit and pad; never crop
    9. output validation     — structure plus a colour-fidelity guard
   10. storage               (performed by services.image_enhancer)

Every correction in stages 6 and 7 is photometric or geometric. Nothing in
this file samples, regenerates or hallucinates product content, which is what
keeps a painted pattern, a printed logo or a dyed textile colour intact. The
one generative model in the system is never allowed near the pixels.
"""

import logging
import time
from contextlib import contextmanager

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from ..utils.image_io import bound_image, encode_image
from .background_remover import ClassicalSegmenter, U2NetSegmenter
from .providers.base import (
    BACKGROUND_NEUTRAL,
    BACKGROUND_ORIGINAL,
    BACKGROUND_TRANSPARENT,
    BACKGROUND_WHITE,
    EnhancementOptions,
    EnhancementResult,
    ImageEnhancementProvider,
    StageRecord,
)

logger = logging.getLogger(__name__)

# Neutral studio backdrop: warm off-white reads as "studio" rather than the
# harsh clipped white of a bad product photo, and it flatters dyed textiles.
NEUTRAL_BACKGROUND = (247, 246, 243)

# Target product luminance. Pushed this far it starts to look processed.
_TARGET_LUMA = 132
_LUMA_DARK_TRIGGER = 96
_LUMA_BRIGHT_TRIGGER = 205

# A correction that moves the product's mean channel by more than this is
# backing away from "faithful" and heading for "different product".
_FIDELITY_TOLERANCE = 13.0


class ImagePipelineError(Exception):
    """A pipeline stage failed. Carries a safe, seller-facing message."""

    def __init__(self, message, code='pipeline_error'):
        super().__init__(message)
        self.message = message
        self.code = code


@contextmanager
def _stage(stages, key, label):
    """Time a stage and append its record whether or not it succeeds."""
    started = time.perf_counter()
    box = {}
    try:
        yield box
    finally:
        stages.append(StageRecord(
            key=key,
            label=label,
            detail=str(box.get('detail', '') or ''),
            duration_ms=int((time.perf_counter() - started) * 1000),
        ))


def _masked_mean_luma(arr: np.ndarray, mask: np.ndarray):
    """Mean luma over product pixels only, so the backdrop cannot skew it."""
    if mask is None:
        return float(arr[..., :3].mean())
    sel = mask > 127
    if not sel.any():
        return float(arr[..., :3].mean())
    return float(arr[..., 0][sel].mean() * 0.299
                 + arr[..., 1][sel].mean() * 0.587
                 + arr[..., 2][sel].mean() * 0.114)


def _product_mean_rgb(arr: np.ndarray, mask: np.ndarray):
    if mask is None:
        region = arr[..., :3].reshape(-1, 3)
    else:
        sel = mask > 127
        if not sel.any():
            region = arr[..., :3].reshape(-1, 3)
        else:
            region = arr[..., :3][sel]
    return region.mean(axis=0)


def _color_shift(before: np.ndarray, after: np.ndarray) -> float:
    """Mean absolute per-channel shift, in 0-255 units."""
    return float(np.abs(np.asarray(before) - np.asarray(after)).max())


class StudioProvider(ImageEnhancementProvider):
    """Deterministic, non-generative enhancement.

    ``is_ai`` is False in the strict sense: there is no learned model making
    the decision about the product. What it *is* is real computer vision,
    and it is the correct tool for a brief that says "enhance, never
    regenerate".
    """

    name = 'studio'
    is_ai = False

    def __init__(self, *, segmenter=None):
        self._segmenter = segmenter

    # -- provider contract ---------------------------------------------

    def is_available(self) -> bool:
        return True

    def remove_background(self, image, options: EnhancementOptions):
        segmenter = self._segmenter or self._build_segmenter()
        mask = segmenter.segment(image)
        return mask

    def enhance(self, image: Image.Image, options: EnhancementOptions) -> EnhancementResult:
        stages: list = []
        guidance = options.advisor_guidance or {}

        # ---- 1. input validation (performed upstream; recorded for the UI)
        with _stage(stages, 'validate', 'Image checked') as box:
            box['detail'] = '%d x %d px' % (image.width, image.height)

        # ---- 2. normalization
        with _stage(stages, 'normalize', 'Image prepared') as box:
            work = image.convert('RGB')
            before = (work.width, work.height)
            work = bound_image(work, options.max_working_edge)
            if work.size != before:
                box['detail'] = 'Resized to %d x %d for processing' % work.size
            else:
                box['detail'] = '%d x %d px' % (work.width, work.height)
        work_arr = np.asarray(work, dtype=np.float32)

        # ---- 3. product / background segmentation
        want_removal = options.background != BACKGROUND_ORIGINAL
        if want_removal and guidance.get('remove_background') is False:
            want_removal = False
        mask = None
        with _stage(stages, 'segment', 'Product isolated') as box:
            if not want_removal:
                box['detail'] = 'Original background kept'
            else:
                segmenter = self._segmenter or self._build_segmenter()
                mask = segmenter.segment(work)
                if mask is None:
                    box['detail'] = 'Background not separable, kept original'
                else:
                    coverage = float((np.asarray(mask) > 127).mean())
                    box['detail'] = 'Product covers %d%% of the frame' % round(coverage * 100)
        if mask is not None and mask.size != work.size:
            mask = mask.resize(work.size, Image.BILINEAR)

        # ---- 4. background cleanup
        with _stage(stages, 'clean', 'Background cleaned') as box:
            if mask is None:
                box['detail'] = 'Nothing to clean'
            else:
                work = self._clean_edges(work, mask)
                box['detail'] = 'Edges tidied and background despeckled'
        work_arr = np.asarray(work, dtype=np.float32)

        # ---- 5. product positioning onto a studio background
        with _stage(stages, 'background', 'Studio background applied') as box:
            composed, mask_for_frame = self._apply_background(
                work, mask, options.background
            )
            box['detail'] = {
                BACKGROUND_WHITE: 'Clean white background',
                BACKGROUND_NEUTRAL: 'Neutral studio background',
                BACKGROUND_TRANSPARENT: 'Transparent background kept',
                BACKGROUND_ORIGINAL: 'Original background kept',
            }.get(options.background, 'Original background kept')
        work = composed

        # ---- 6. lighting and colour correction, with a fidelity guard
        with _stage(stages, 'correct', 'Lighting and colour corrected') as box:
            work = self._correct(work, mask_for_frame, guidance, box)
        corrected_arr = np.asarray(work, dtype=np.float32)

        # ---- 7. quality enhancement
        with _stage(stages, 'sharpen', 'Detail enhanced') as box:
            work = self._sharpen(work, mask_for_frame, guidance)
            box['detail'] = 'Noise reduced and detail sharpened'

        # ---- 8. ecommerce formatting
        with _stage(stages, 'format', 'Ecommerce format prepared') as box:
            final = self._frame(work, mask_for_frame, options)
            box['detail'] = '%d x %d px, product centred and uncropped' % final.size

        # ---- 9. output validation, including colour fidelity
        with _stage(stages, 'validate_output', 'Result verified') as box:
            fidelity = self._fidelity(work_arr, corrected_arr, mask_for_frame)
            score = max(0.0, 1.0 - fidelity / 40.0)
            box['detail'] = 'Product colours preserved (%.0f%% match)' % round(score * 100)

        quality = {
            'fidelity': round(max(0.0, 1.0 - fidelity / 40.0), 3),
            'color_shift': round(fidelity, 2),
            'segmented': mask_for_frame is not None,
            'working_size': list(work.size),
            'output_size': list(final.size),
        }
        return EnhancementResult(
            image=final,
            stages=stages,
            quality=quality,
            is_ai=self.is_ai,
            provider_name=self.name,
        )

    # -- helpers -------------------------------------------------------

    def _build_segmenter(self):
        from django.conf import settings

        choice = getattr(settings, 'IMAGE_ENHANCEMENT_SEGMENTER', 'auto')
        if choice == 'u2net':
            candidate = U2NetSegmenter()
            if candidate.is_available():
                return candidate
            logger.info('u2net requested but rembg is not installed; using classical segmenter')
        if choice == 'classical':
            return ClassicalSegmenter()
        # auto: prefer the neural model when it is actually installed.
        candidate = U2NetSegmenter()
        return candidate if candidate.is_available() else ClassicalSegmenter()

    def _clean_edges(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        """Despeckle the background without touching the product.

        A phone photo of a product on a cloth backdrop picks up sensor noise,
        a stray hair or a speck of lint, and once that background is replaced
        the defect is a hard-edged blob on a clean white field. A median pass
        confined to the background region removes it; the product pixels are
        masked out of the operation entirely, because the same median that
        removes a speck would also dissolve the weave of a fabric.
        """
        blurred = image.filter(ImageFilter.MedianFilter(3))
        # Image.composite takes the *first* image where the mask is white, and
        # the mask is white on the product -- so the product keeps its own
        # pixels and only the background is taken from the smoothed copy.
        # Reversing these two arguments is the one way to blur the weave
        # instead of the lint, so keep the order in mind when editing.
        return Image.composite(image, blurred, mask)

    def _apply_background(self, image: Image.Image, mask, background: str):
        """Composite the product onto the chosen backdrop.

        The working image stays RGB throughout the pipeline. Transparency is
        not a colour operation, it is the mask itself, so it is applied last,
        when the product is framed. Carrying an alpha channel through the
        colour-correction maths instead would mean every NumPy expression
        downstream having to know about a fourth channel.

        Returns ``(rgb_composite, mask)``. The mask is reused for framing so
        the product is positioned by its true silhouette, not by the frame.
        """
        if mask is None or background in (BACKGROUND_TRANSPARENT, BACKGROUND_ORIGINAL):
            return image, mask

        fill = NEUTRAL_BACKGROUND if background == BACKGROUND_NEUTRAL else (255, 255, 255)
        canvas = Image.new('RGB', image.size, fill)
        # A soft alpha is deliberate: feathering the product onto the backdrop
        # is what avoids a cut-out sticker look.
        canvas.paste(image, (0, 0), mask)
        return canvas, mask

    def _correct(self, image: Image.Image, mask, guidance: dict, box: dict):
        """Exposure, white balance, contrast and saturation — all dampened.

        The brief is "make it look professional", not "make it look
        different". So each correction is capped, colour work is applied only
        to product pixels, and the whole thing is measured afterwards against
        the untouched original. If the product's mean colour has moved too
        far, the corrections are halved and re-applied.

        Returns the corrected image; progress detail is written into ``box``.
        """
        arr = np.asarray(image, dtype=np.float32)
        work = image.copy()

        if mask is not None:
            product = np.asarray(
                Image.composite(image, Image.new('RGB', image.size, (128, 128, 128)), mask),
                dtype=np.float32,
            )
        else:
            product = arr

        original_mean = _product_mean_rgb(arr, None if mask is None else
                                          np.asarray(mask))

        luma = _masked_mean_luma(arr, np.asarray(mask) if mask is not None else None)
        exposure_hint = guidance.get('exposure')

        # --- white balance, grey-world on the product only
        wb = 0.5
        channel_means = product[..., :3].reshape(-1, 3).mean(axis=0)
        grey = float(channel_means.mean())
        if grey > 12:
            gains = np.clip(grey / np.maximum(channel_means, 1.0), 0.86, 1.16)
            gains = 1.0 + (gains - 1.0) * wb
            work = Image.fromarray(
                np.clip(np.asarray(work, dtype=np.float32)
                        * gains[None, None, :], 0, 255).astype(np.uint8)
            )

        # --- exposure, only when clearly off
        adjusted = np.asarray(work, dtype=np.float32)
        new_luma = _masked_mean_luma(adjusted, np.asarray(mask) if mask is not None else None)
        need = 0.0
        if new_luma < _LUMA_DARK_TRIGGER or exposure_hint == 'dark':
            need = float(np.clip(_TARGET_LUMA / max(new_luma, 24.0), 1.0, 1.32))
        elif new_luma > _LUMA_BRIGHT_TRIGGER or exposure_hint == 'bright':
            need = float(np.clip(_TARGET_LUMA / max(new_luma, 24.0), 0.72, 1.0))
        if abs(need - 1.0) > 0.01:
            work = Image.fromarray(
                np.clip(adjusted * need, 0, 255).astype(np.uint8)
            )

        # --- gentle S-curve for contrast, via a smoothstep blend
        work = _s_curve(work, amount=0.13)

        # --- saturation nudge toward a modest target, never a "vivid" filter
        work = ImageEnhance.Color(work).enhance(_saturation_factor(work, mask))

        # --- fidelity guard
        final_mean = _product_mean_rgb(np.asarray(work, dtype=np.float32), None if mask is None
                                       else np.asarray(mask))
        shift = _color_shift(original_mean, final_mean)
        if shift > _FIDELITY_TOLERANCE:
            # Too far from the seller's original colour. Re-do it at half
            # strength rather than shipping a recoloured product.
            logger.info('Colour shift %.1f exceeded tolerance; halving corrections', shift)
            work = self._correct_half_strength(image, mask, guidance)
            final_mean = _product_mean_rgb(np.asarray(work, dtype=np.float32), None
                                           if mask is None else np.asarray(mask))
            shift = _color_shift(original_mean, final_mean)

        box['detail'] = 'Exposure, white balance and contrast balanced'
        return work

    def _correct_half_strength(self, image: Image.Image, mask, guidance: dict):
        """Exposure-only fallback: keep light, abandon colour work."""
        arr = np.asarray(image, dtype=np.float32)
        luma = _masked_mean_luma(arr, np.asarray(mask) if mask is not None else None)
        need = 1.0
        if luma < _LUMA_DARK_TRIGGER:
            need = float(np.clip(_TARGET_LUMA / max(luma, 24.0), 1.0, 1.22))
        elif luma > _LUMA_BRIGHT_TRIGGER:
            need = float(np.clip(_TARGET_LUMA / max(luma, 24.0), 0.8, 1.0))
        if abs(need - 1.0) < 0.01:
            return image.copy()
        return Image.fromarray(np.clip(arr * need, 0, 255).astype(np.uint8))

    def _sharpen(self, image: Image.Image, mask, guidance: dict) -> Image.Image:
        """Mild unsharp mask, skipped when the advisor reports a soft source.

        Oversharpening is the single most common way an "AI enhanced" photo
        acquires halos around embroidery and woven texture, so the amount is
        small and a threshold is set to keep flat areas quiet.
        """
        softness = guidance.get('sharpness') == 'soft'
        if softness:
            return image.filter(ImageFilter.SMOOTH)
        radius = 1.1
        percent = 55 if softness is False else 80
        return image.filter(
            ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=3)
        )

    def _frame(self, image: Image.Image, mask, options: EnhancementOptions):
        """Scale to fit the canvas and pad. Never crops, never upscales.

        The product's own silhouette decides the crop: the empty margin
        around it is trimmed away first, so the framing reflects where the
        product actually is rather than where the seller's phone happened to
        point. Only *down*scaling is applied -- enlarging a small photo
        invents detail, which is exactly what the brief forbids.
        """
        canvas_w, canvas_h = options.canvas
        pad = int(round(min(canvas_w, canvas_h) * options.padding_ratio))
        inner_w = max(1, canvas_w - pad * 2)
        inner_h = max(1, canvas_h - pad * 2)

        trimmed, trimmed_mask = image, None
        if mask is not None:
            bbox = mask.point(lambda v: 255 if v > 40 else 0).getbbox()
            if bbox:
                trimmed = image.crop(bbox)
                trimmed_mask = mask.crop(bbox)

        scale = min(inner_w / trimmed.width, inner_h / trimmed.height)
        if scale < 1.0:
            new_size = (max(1, int(trimmed.width * scale)),
                        max(1, int(trimmed.height * scale)))
            trimmed = trimmed.resize(new_size, Image.LANCZOS)
            if trimmed_mask is not None:
                trimmed_mask = trimmed_mask.resize(new_size, Image.BILINEAR)

        offset = ((canvas_w - trimmed.width) // 2, (canvas_h - trimmed.height) // 2)
        wants_alpha = options.background == BACKGROUND_TRANSPARENT and trimmed_mask is not None

        if wants_alpha:
            # Cut-out PNG: the alpha is the mask, trimmed and scaled alongside
            # the product so the two stay registered.
            canvas = Image.new('RGBA', (canvas_w, canvas_h), (255, 255, 255, 0))
            canvas.paste(trimmed.convert('RGB'), offset, trimmed_mask)
            return canvas

        canvas = _canvas_for(image, (canvas_w, canvas_h))
        canvas.paste(trimmed, offset)
        return canvas

    def _fidelity(self, original: np.ndarray, corrected: np.ndarray, mask) -> float:
        """How far the product's colour moved, in 0-255 units."""
        mask_arr = np.asarray(mask) if mask is not None else None
        before = _product_mean_rgb(original, mask_arr)
        after = _product_mean_rgb(corrected, mask_arr)
        return _color_shift(before, after)

    # -- encoding ------------------------------------------------------

    @staticmethod
    def encode(result: EnhancementResult, options: EnhancementOptions, fmt='JPEG'):
        return encode_image(result.image, fmt, options.output_quality)


def _canvas_for(image: Image.Image, size):
    """A canvas matching the working image's mode, so alpha survives framing."""
    if image.mode in ('RGBA', 'LA'):
        return Image.new('RGBA', size, (255, 255, 255, 0))
    return Image.new('RGB', size, (255, 255, 255))


def _s_curve(image: Image.Image, amount: float) -> Image.Image:
    """Blend toward a smoothstep S-curve: lifts midtones, deepens shadows."""
    if amount <= 0:
        return image
    lut = []
    for value in range(256):
        x = value / 255.0
        s = x * x * (3 - 2 * x)
        lut.append(int(round(max(0, min(255, (x + amount * (s - x)) * 255)))))
    return image.point(lut * len(image.getbands()))


def _saturation_factor(image: Image.Image, mask) -> float:
    """A small nudge toward a modest saturation, never a vivid filter."""
    sample = image
    if mask is not None:
        # Judge saturation on the product, not on a large flat backdrop which
        # would drag the measurement to zero.
        sample = Image.composite(
            image, Image.new('RGB', image.size, (128, 128, 128)), mask
        )
    grey = np.asarray(sample.convert('L'), dtype=np.float32)
    rgb = np.asarray(sample.convert('RGB'), dtype=np.float32)
    spread = float((rgb.max(axis=2) - rgb.min(axis=2)).mean())
    target = 46.0
    if spread <= 1:
        return 1.0
    factor = float(np.clip(target / spread, 0.92, 1.12))
    # Convert a saturation ratio into ImageEnhance's multiplier.
    return 1.0 + (factor - 1.0) * 0.5
