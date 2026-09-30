"""Service layer for the image enhancement feature."""

from .image_enhancer import EnhancementError, EnhancementOutcome, run_enhancement
from .providers import BACKGROUNDS, build_options, get_provider
from .storage import delete_quietly, store_enhanced, store_original
from .voice_text import (
    VoiceTextError,
    generate_product_description,
    generate_product_tags,
    generate_seo_keywords,
    rewrite_for_seo,
    text_completion,
    text_to_speech,
    transcribe_audio,
)

__all__ = [
    'BACKGROUNDS',
    'EnhancementError',
    'EnhancementOutcome',
    'VoiceTextError',
    'build_options',
    'delete_quietly',
    'generate_product_description',
    'generate_product_tags',
    'generate_seo_keywords',
    'get_provider',
    'rewrite_for_seo',
    'run_enhancement',
    'store_enhanced',
    'store_original',
    'text_completion',
    'text_to_speech',
    'transcribe_audio',
]
