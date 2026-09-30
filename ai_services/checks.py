"""Deployment guards for the image enhancement pipeline.

The one thing that must never happen is a live store quietly showing demo
output to a real seller, so that is a hard ``ERROR`` when ``DEBUG`` is off.
Everything else is advisory: a missing optional dependency or a missing
OpenRouter key degrades the pipeline rather than breaking it, and the
pipeline is designed to work with neither.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

DEMO = 'demo'
KNOWN_PROVIDERS = {'studio', DEMO}
KNOWN_SEGMENTERS = {'auto', 'classical', 'u2net'}
KNOWN_BACKGROUNDS = {'white', 'neutral', 'transparent', 'original'}
KNOWN_ADVISORS = {'auto', 'openrouter', 'none'}

E001 = 'ai_services.E001'   # demo provider in production
E002 = 'ai_services.E002'   # unknown provider

W001 = 'ai_services.W001'   # unknown segmenter
W002 = 'ai_services.W002'   # u2net requested, rembg missing
W003 = 'ai_services.W003'   # unknown advisor
W004 = 'ai_services.W004'   # advisor enabled without a key
W005 = 'ai_services.W005'   # unknown background


@register('ai_services')
def check_production_configuration(app_configs, **kwargs):
    messages = []
    provider = getattr(settings, 'IMAGE_ENHANCEMENT_PROVIDER', 'studio')
    segmenter = getattr(settings, 'IMAGE_ENHANCEMENT_SEGMENTER', 'auto')
    advisor = getattr(settings, 'IMAGE_ENHANCEMENT_ADVISOR', 'auto')
    background = getattr(settings, 'IMAGE_ENHANCEMENT_BACKGROUND', 'white')
    api_key = getattr(settings, 'AI_API_KEY', '')

    if provider not in KNOWN_PROVIDERS:
        messages.append(
            Error(
                'Unknown IMAGE_ENHANCEMENT_PROVIDER.',
                hint='Use one of: %s.' % ', '.join(sorted(KNOWN_PROVIDERS)),
                id=E002,
            )
        )
    elif provider == DEMO and not settings.DEBUG:
        # The demo provider is deterministic local processing, not AI. It must
        # never be what a real customer is shown without someone deciding so.
        messages.append(
            Error(
                'IMAGE_ENHANCEMENT_PROVIDER is "demo" with DEBUG off. Sellers '
                'would be shown non-AI placeholder output as a real result.',
                hint='Set IMAGE_ENHANCEMENT_PROVIDER=studio in production.',
                id=E001,
            )
        )

    if segmenter not in KNOWN_SEGMENTERS:
        messages.append(
            Warning(
                'Unknown IMAGE_ENHANCEMENT_SEGMENTER.',
                hint='Use one of: %s.' % ', '.join(sorted(KNOWN_SEGMENTERS)),
                id=W001,
            )
        )
    elif segmenter == 'u2net':
        try:
            import rembg  # noqa: F401
        except ImportError:
            messages.append(
                Warning(
                    'IMAGE_ENHANCEMENT_SEGMENTER=u2net but the optional '
                    '"rembg" package is not installed.',
                    hint='Run "pip install rembg" for neural background '
                         'removal, or use the default (auto).',
                    id=W002,
                )
            )

    if advisor not in KNOWN_ADVISORS:
        messages.append(
            Warning(
                'Unknown IMAGE_ENHANCEMENT_ADVISOR.',
                hint='Use one of: %s.' % ', '.join(sorted(KNOWN_ADVISORS)),
                id=W003,
            )
        )
    elif advisor != 'none' and not api_key:
        messages.append(
            Warning(
                'The OpenRouter vision advisor is enabled but AI_API_KEY is '
                'empty, so the pipeline will use its own conservative '
                'defaults. Enhancement still works.',
                hint='Set AI_API_KEY, or set IMAGE_ENHANCEMENT_ADVISOR=none '
                     'to silence this.',
                id=W004,
            )
        )

    if background not in KNOWN_BACKGROUNDS:
        messages.append(
            Warning(
                'Unknown IMAGE_ENHANCEMENT_BACKGROUND.',
                hint='Use one of: %s.' % ', '.join(sorted(KNOWN_BACKGROUNDS)),
                id=W005,
            )
        )

    return messages
