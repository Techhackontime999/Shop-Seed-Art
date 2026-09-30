"""Non-AI fallback provider for local development.

This provider is deterministic image processing, not AI, and it says so.
``EnhancementResult.is_ai`` is False, the frontend labels the output as a
demo, and ``ai_services.checks`` raises a Django system-check **error** if
this provider is selected with ``DEBUG`` off — so a production store can
never quietly hand placeholder output to a real seller.

It is not a stub that returns a placeholder image: it runs a genuine
neutral-background composite and a gentle exposure lift, so the rest of the
pipeline (storage, before/after, draft selection) is exercised for real
during development.
"""

import numpy as np
from PIL import Image

from ...utils.image_io import bound_image
from ..image_processor import NEUTRAL_BACKGROUND, _canvas_for
from .base import (
    BACKGROUND_NEUTRAL,
    BACKGROUND_WHITE,
    EnhancementOptions,
    EnhancementResult,
    ImageEnhancementProvider,
    StageRecord,
)


class DemoProvider(ImageEnhancementProvider):
    """Clearly-labelled, non-AI fallback."""

    name = 'demo'
    is_ai = False

    def is_available(self) -> bool:
        return True

    def remove_background(self, image, options: EnhancementOptions):
        # Deliberately no segmentation: the demo must not claim the one
        # capability that genuinely needs a model.
        return None

    def enhance(self, image: Image.Image, options: EnhancementOptions) -> EnhancementResult:
        work = bound_image(image.convert('RGB'), min(options.max_working_edge, 1200))
        arr = np.asarray(work, dtype=np.float32)
        luma = float(arr[..., 0].mean() * 0.299 + arr[..., 1].mean() * 0.587
                     + arr[..., 2].mean() * 0.114)
        stages = [StageRecord(key='validate', label='Image checked',
                              detail='%d x %d px' % (work.width, work.height))]

        if luma < 100:
            work = Image.fromarray(
                np.clip(arr * 1.12, 0, 255).astype(np.uint8)
            )
        stages.append(StageRecord(key='normalize', label='Image prepared',
                                  detail='Demo normalisation only'))

        fill = (255, 255, 255) if options.background == BACKGROUND_WHITE else NEUTRAL_BACKGROUND
        if options.background in (BACKGROUND_WHITE, BACKGROUND_NEUTRAL):
            canvas = Image.new('RGB', work.size, fill)
            # A vignette-free flat backdrop, with the photo faded over it so the
            # seller can see this is a composite and not a real cut-out.
            faded = Image.blend(work, Image.new('RGB', work.size, fill), 0.72)
            canvas.paste(faded, (0, 0))
            work = canvas
        stages.append(StageRecord(key='background', label='Demo background applied',
                                  detail='Not a real background removal'))

        canvas_w, canvas_h = options.canvas
        pad = int(round(min(canvas_w, canvas_h) * options.padding_ratio))
        scale = min((canvas_w - pad * 2) / work.width, (canvas_h - pad * 2) / work.height)
        if scale < 1:
            work = work.resize((max(1, int(work.width * scale)),
                                max(1, int(work.height * scale))), Image.LANCZOS)
        final = _canvas_for(work, (canvas_w, canvas_h))
        final.paste(work, ((canvas_w - work.width) // 2, (canvas_h - work.height) // 2))
        stages.append(StageRecord(key='format', label='Ecommerce format prepared',
                                  detail='%d x %d px' % final.size))

        return EnhancementResult(
            image=final,
            stages=stages,
            quality={'fidelity': 1.0, 'color_shift': 0.0, 'segmented': False,
                     'demo': True},
            is_ai=False,
            provider_name=self.name,
        )
