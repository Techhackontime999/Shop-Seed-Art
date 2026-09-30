"""The enhancement job: one seller's photo, on its way to a draft.

A job is deliberately *not* a Product. Nothing here is ever published by this
app; the seller has to choose an image in the studio, and product creation
stays a separate, explicit action. Keeping the two apart is what makes it
impossible for a failed or unreviewed enhancement to leak into a live listing.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .services.providers.base import BACKGROUNDS, BACKGROUND_WHITE


class EnhancementStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'


class Selection(models.TextChoices):
    NONE = 'none', 'No choice yet'
    ORIGINAL = 'original', 'Keep the original'
    ENHANCED = 'enhanced', 'Use the enhanced image'


class ImageEnhancementJob(models.Model):
    """A single enhancement run and its draft artefacts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='image_enhancement_jobs',
    )

    status = models.CharField(
        max_length=16, choices=EnhancementStatus.choices,
        default=EnhancementStatus.PENDING, db_index=True,
    )

    # Both files live under ai-enhancements/, never under products/, so a
    # draft can never be picked up by anything that lists published media.
    original = models.FileField(upload_to='ai-enhancements/originals/%Y/%m/%d')
    enhanced = models.FileField(upload_to='ai-enhancements/enhanced/%Y/%m/%d', blank=True)

    background = models.CharField(
        max_length=16, choices=[(b, b) for b in BACKGROUNDS],
        default=BACKGROUND_WHITE,
    )
    selection = models.CharField(
        max_length=16, choices=Selection.choices, default=Selection.NONE,
    )

    # The stages the pipeline actually ran, in order. The frontend renders
    # these verbatim, which is why they are stored rather than reconstructed.
    stages = models.JSONField(default=list, blank=True)
    quality = models.JSONField(default=dict, blank=True)

    provider = models.CharField(max_length=32, blank=True)
    is_ai = models.BooleanField(default=False)
    advisor_notes = models.CharField(max_length=240, blank=True)

    error_code = models.CharField(max_length=48, blank=True)
    error_message = models.CharField(max_length=240, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['seller', '-created_at']),
        ]

    def __str__(self):
        return 'Enhancement %s (%s)' % (self.id, self.status)

    # -- state --------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        return self.status == EnhancementStatus.COMPLETED

    @property
    def has_enhanced(self) -> bool:
        return bool(self.enhanced)

    def mark_failed(self, code: str, message: str) -> None:
        self.status = EnhancementStatus.FAILED
        self.error_code = (code or '')[:48]
        self.error_message = (message or '')[:240]
        self.save(update_fields=['status', 'error_code', 'error_message', 'updated_at'])

    def as_dict(self) -> dict:
        """The JSON shape the studio frontend consumes."""
        return {
            'id': str(self.id),
            'status': self.status,
            'background': self.background,
            'selection': self.selection,
            'stages': self.stages or [],
            'quality': self.quality or {},
            'provider': self.provider,
            'is_ai': self.is_ai,
            'original_url': self.original.url if self.original else None,
            'enhanced_url': self.enhanced.url if self.enhanced else None,
            'error': {
                'code': self.error_code,
                'message': self.error_message,
            } if self.error_code else None,
        }
