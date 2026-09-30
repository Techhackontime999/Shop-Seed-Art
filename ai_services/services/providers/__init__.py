"""Provider registry.

``get_provider()`` is the only place in the codebase that knows which
implementation is configured, so adding a vendor is a new class plus one
entry here.
"""

import logging

from django.conf import settings

from .base import (
    BACKGROUNDS,
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


def build_options(**overrides) -> EnhancementOptions:
    """Build pipeline options from settings, clamped to sane ranges."""
    canvas = getattr(settings, 'IMAGE_ENHANCEMENT_CANVAS', (1000, 1000))
    try:
        canvas = (int(canvas[0]), int(canvas[1]))
    except Exception:
        canvas = (1000, 1000)

    def _clamp(value, low, high, fallback):
        try:
            return max(low, min(high, int(value)))
        except (TypeError, ValueError):
            return fallback

    background = getattr(settings, 'IMAGE_ENHANCEMENT_BACKGROUND', BACKGROUND_WHITE)
    if background not in BACKGROUNDS:
        background = BACKGROUND_WHITE

    return EnhancementOptions(
        background=background,
        product_category=overrides.get('product_category', 'generic'),
        advisor_guidance=overrides.get('advisor_guidance') or {},
        canvas=canvas,
        padding_ratio=max(0.0, min(0.2, float(
            getattr(settings, 'IMAGE_ENHANCEMENT_PADDING', 0.06)))),
        max_working_edge=_clamp(
            getattr(settings, 'IMAGE_ENHANCEMENT_WORKING_MAX_EDGE', 1600),
            640, 2400, 1600),
        output_quality=_clamp(
            getattr(settings, 'IMAGE_ENHANCEMENT_QUALITY', 90), 70, 95, 90),
    )


def get_provider(name: str = None) -> ImageEnhancementProvider:
    """Instantiate the configured provider.

    An unrecognised name is a configuration error, so it falls back to the
    real pipeline rather than to the demo provider.
    """
    chosen = (name or getattr(settings, 'IMAGE_ENHANCEMENT_PROVIDER', 'studio')).lower()

    if chosen == 'demo':
        from .demo import DemoProvider

        return DemoProvider()

    if chosen == 'studio':
        from ..image_processor import StudioProvider

        return StudioProvider()

    logger.warning('Unknown IMAGE_ENHANCEMENT_PROVIDER=%r; using studio', chosen)
    from ..image_processor import StudioProvider

    return StudioProvider()


__all__ = [
    'BACKGROUNDS',
    'BACKGROUND_NEUTRAL',
    'BACKGROUND_ORIGINAL',
    'BACKGROUND_TRANSPARENT',
    'BACKGROUND_WHITE',
    'EnhancementOptions',
    'EnhancementResult',
    'ImageEnhancementProvider',
    'StageRecord',
    'build_options',
    'get_provider',
]
