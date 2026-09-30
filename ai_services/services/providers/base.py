"""Enhancement provider interface.

A provider turns a decoded photo plus a set of options into a finished
ecommerce image and a log of the stages it actually ran. Swapping vendors
means writing a new class and pointing ``IMAGE_ENHANCEMENT_PROVIDER`` at it
— no view, URL or template changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from PIL import Image

# Background treatments. ``transparent`` is a real option, not a flourish:
# marketplaces that support cut-out PNGs get one, and the same pipeline
# serves them.
BACKGROUND_WHITE = 'white'
BACKGROUND_NEUTRAL = 'neutral'
BACKGROUND_TRANSPARENT = 'transparent'
BACKGROUND_ORIGINAL = 'original'
BACKGROUNDS = (
    BACKGROUND_WHITE,
    BACKGROUND_NEUTRAL,
    BACKGROUND_TRANSPARENT,
    BACKGROUND_ORIGINAL,
)


@dataclass
class StageRecord:
    """One step the provider genuinely performed.

    The frontend renders these verbatim. Nothing is invented here, which is
    what lets the UI show real progress instead of a fake percentage.
    """

    key: str
    label: str
    detail: str = ''
    duration_ms: int = 0

    def as_dict(self):
        return {
            'key': self.key,
            'label': self.label,
            'detail': self.detail,
            'duration_ms': self.duration_ms,
        }


@dataclass
class EnhancementOptions:
    """Seller-facing knobs. Every field is validated and clamped by the pipeline."""

    background: str = BACKGROUND_WHITE
    product_category: str = 'generic'
    advisor_guidance: dict = field(default_factory=dict)
    canvas: tuple = (1000, 1000)
    padding_ratio: float = 0.06
    max_working_edge: int = 1600
    output_quality: int = 90

    def as_dict(self):
        return {
            'background': self.background,
            'product_category': self.product_category,
            'canvas': list(self.canvas),
            'padding_ratio': self.padding_ratio,
        }


@dataclass
class EnhancementResult:
    """What a provider hands back to the orchestration layer."""

    image: Image.Image
    stages: List[StageRecord] = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    is_ai: bool = False
    provider_name: str = 'unknown'

    def as_dict(self):
        return {
            'provider': self.provider_name,
            'is_ai': self.is_ai,
            'stages': [s.as_dict() for s in self.stages],
            'quality': self.quality,
        }


class ImageEnhancementProvider(ABC):
    """Contract every provider implements.

    ``is_ai`` is the honesty flag: the demo provider sets it False so the
    frontend can never present placeholder output as an AI result.
    """

    name = 'base'
    is_ai = False

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can run right now."""

    @abstractmethod
    def remove_background(self, image: Image.Image, options: EnhancementOptions):
        """Return a product mask ('L' image, 255 = product), or ``None``.

        Returning a mask rather than a flat cut-out image is what lets the
        pipeline reuse the product's silhouette for framing and for
        colour-fidelity checks instead of re-segmenting. ``None`` means "I
        could not isolate this product", which the pipeline treats as a
        signal to keep the seller's own background rather than to guess.
        """

    @abstractmethod
    def enhance(self, image: Image.Image, options: EnhancementOptions) -> EnhancementResult:
        """Run the full pipeline and return the finished image."""
