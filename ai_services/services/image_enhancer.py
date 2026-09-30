"""The enhancement orchestrator.

Owns the sequence and the failure handling, and nothing else: the actual
imaging work lives in the providers, the segmenter and the pipeline. It is a
plain function over bytes so it can be unit-tested without a request, a
session or the database.

The order is deliberate and load-bearing:

1. Validate the *untrusted* upload before anything decodes it fully.
2. Decode once, stripped of metadata.
3. Ask the vision advisor for a reading of this specific photo (optional, and
   never allowed to fail the request).
4. Run the deterministic pipeline.
5. Re-validate the result.
6. Store original and enhanced to separate paths, rolling back the second if
   the first write fails.

The OpenRouter advisor sits at step 3 and *only* at step 3. It receives a
downscaled copy and returns a small set of enumerated parameters. It has no
path to the output image.
"""

import logging
import time
from dataclasses import dataclass, field

from django.conf import settings

from ..utils.image_io import encode_image, open_image
from ..utils.image_validation import ImageValidationError, validate_upload
from .providers import build_options, get_provider
from .storage import StorageError, delete_quietly, store_enhanced, store_original

logger = logging.getLogger(__name__)


class EnhancementError(Exception):
    """A stage failed. Carries a seller-safe code and message."""

    def __init__(self, code, message, detail=''):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass
class EnhancementOutcome:
    original_name: str
    enhanced_name: str
    original_format: str
    output_format: str
    stages: list = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    provider: str = ''
    is_ai: bool = False
    advisor: dict = field(default_factory=dict)
    duration_ms: int = 0


def _advisor_guidance(image_bytes: bytes) -> dict:
    """Optionally consult the vision model. Any failure yields no guidance.

    The advisor is an optimisation. A deployment with no API key, a rate
    limit, a timeout or a hallucinating model must still enhance images, so
    every path out of here except success is swallowed into ``{}``.
    """
    if not getattr(settings, 'IMAGE_ENHANCEMENT_ADVISOR_ENABLED', False):
        return {}
    if not getattr(settings, 'AI_API_KEY', ''):
        return {}
    try:
        from ..clients.openrouter import OpenRouterClient

        client = OpenRouterClient(
            timeout=getattr(settings, 'AI_TIMEOUT', 20),
            max_retries=1,
        )
        return client.image_guidance(
            image_bytes,
            timeout=getattr(settings, 'IMAGE_ENHANCEMENT_ADVISOR_TIMEOUT', 6),
        )
    except Exception:
        logger.warning('Vision advisor failed; continuing without it', exc_info=True)
        return {}


def run_enhancement(
    *,
    upload,
    job_id: str,
    attempt: int = 1,
    background: str = None,
    product_category: str = 'generic',
) -> EnhancementOutcome:
    """Validate, enhance, encode and store. Raises :class:`EnhancementError`."""
    started = time.perf_counter()

    try:
        validated = validate_upload(
            upload,
            max_bytes=getattr(settings, 'IMAGE_ENHANCEMENT_MAX_BYTES', 25 * 1024 * 1024),
            max_pixels=getattr(settings, 'IMAGE_ENHANCEMENT_MAX_PIXELS', 40_000_000),
        )
    except ImageValidationError:
        # Already seller-safe; propagate unchanged.
        raise

    upload.seek(0)
    raw = upload.read()
    try:
        source = open_image(raw)
    except Exception as exc:
        raise EnhancementError(
            'corrupt_image',
            'That photo could not be processed. Please choose another one.',
            detail=str(exc),
        ) from exc

    guidance = _advisor_guidance(raw)
    if background:
        # An explicit seller choice beats the advisor's opinion.
        guidance = dict(guidance)
        guidance.pop('remove_background', None)
    options = build_options(
        product_category=product_category,
        advisor_guidance=guidance,
    )
    if background:
        options.background = background

    provider = get_provider()
    if not provider.is_available():
        raise EnhancementError(
            'provider_unavailable',
            'Image enhancement is not available right now. Please try again shortly.',
        )

    try:
        result = provider.enhance(source, options)
    except Exception as exc:
        logger.exception('Enhancement pipeline failed')
        raise EnhancementError(
            'enhancement_failed',
            'We could not enhance that photo. Please try another image.',
            detail='%s: %s' % (type(exc).__name__, exc),
        ) from exc

    if result.image is None or result.image.width == 0:
        raise EnhancementError(
            'empty_result', 'The enhancement produced an empty image.',
        )

    # A transparent cut-out is only meaningful as PNG; everything else goes
    # out as a high-quality, 4:4:4 JPEG.
    wants_alpha = options.background == 'transparent'
    output_format = 'PNG' if wants_alpha else 'JPEG'
    try:
        enhanced_bytes = encode_image(result.image, output_format, options.output_quality)
    except Exception as exc:
        raise EnhancementError(
            'encoding_failed', 'The enhanced photo could not be saved.',
            detail=str(exc),
        ) from exc

    # --- 9b. verify what we are about to publish
    try:
        verified = open_image(enhanced_bytes)
        if verified.width < 64 or verified.height < 64:
            raise EnhancementError('empty_result', 'The enhanced photo came out too small.')
    except EnhancementError:
        raise
    except Exception as exc:
        raise EnhancementError(
            'output_invalid', 'The enhanced photo failed verification.',
            detail=str(exc),
        ) from exc

    # --- 10. store
    try:
        original_name = store_original(raw, validated.format, job_id)
    except StorageError as exc:
        raise EnhancementError(
            'storage_failed', 'We could not save your original photo.', detail=str(exc),
        ) from exc

    try:
        enhanced_name = store_enhanced(enhanced_bytes, output_format, job_id, attempt)
    except StorageError as exc:
        # The original is no longer referenced by anything, so do not leave it
        # orphaned in the bucket.
        delete_quietly(original_name)
        raise EnhancementError(
            'storage_failed', 'We could not save the enhanced photo.', detail=str(exc),
        ) from exc

    return EnhancementOutcome(
        original_name=original_name,
        enhanced_name=enhanced_name,
        original_format=validated.format,
        output_format=output_format,
        stages=[s.as_dict() for s in result.stages],
        quality=result.quality,
        provider=result.provider_name,
        is_ai=result.is_ai,
        advisor=guidance,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
