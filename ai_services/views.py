"""JSON endpoints for the AI services (image, voice, text).

Conventions follow the rest of the project: session authentication via
``@login_required``, ``@require_POST`` for mutations, and plain
``JsonResponse``. No DRF is introduced for these endpoints.

Security notes:
* Every query is scoped with ``seller=request.user``.
* Nothing about uploads is trusted; validation decides from bytes.
* Internal detail goes to the log; the seller sees a short, safe message.
* Endpoints are rate-limited via ``throttle_allows`` so 429 is JSON.
"""

import io
import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import JsonResponse, FileResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.throttle import throttle_allows
from core.sanitizers import sanitize_html

from .models import EnhancementStatus, ImageEnhancementJob, Selection
from .services.image_enhancer import EnhancementError, run_enhancement
from .services.providers.base import BACKGROUNDS
from .services.speech_to_text import SpeechError, transcribe as transcribe_speech
from .services.storage import StorageError, store_original
from .services.voice_text import VoiceTextError, generate_product_catalog, generate_product_description, generate_product_tags, generate_seo_keywords, rewrite_for_seo, text_completion, text_to_speech, transcribe_audio
from .utils.image_validation import ImageValidationError, validate_upload

logger = logging.getLogger(__name__)

def _error(code, message, status=400, **extra):
    payload = {'success': False, 'error': {'code': code, 'message': message}}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _get_owned_job(request, job_id):
    """Fetch a job the caller owns, or 404.

    Scoping on the owner in the query (rather than fetching then comparing)
    means a wrong-owner id is indistinguishable from a missing one, so the
    endpoint cannot be used to probe for valid job ids.
    """
    return get_object_or_404(
        ImageEnhancementJob.objects.filter(seller=request.user), pk=job_id
    )


@csrf_protect
@require_POST
@login_required
def enhance(request):
    """Accept a photo, run the pipeline, return both images and the stage log."""
    if not throttle_allows(
        'ai_image_enhance', request,
        max_requests=getattr(settings, 'IMAGE_ENHANCEMENT_RATE_LIMIT', 6), window_seconds=60,
    ):
        return _error(
            'rate_limited',
            'Too many enhancements at once. Please wait a minute and try again.',
            status=429,
        )

    upload = request.FILES.get('image')
    if upload is None:
        return _error('missing_file', 'Please choose a photo of your product.')

    background = (request.POST.get('background') or '').strip().lower()
    if background and background not in BACKGROUNDS:
        return _error('bad_background', 'That background option is not available.')

    product_category = (request.POST.get('category') or 'generic').strip()[:40]

    # A row is created up front so the artefacts are attributable even if the
    # process dies mid-pipeline, which also gives the client a stable id to
    # poll.
    job = ImageEnhancementJob.objects.create(
        seller=request.user,
        status=EnhancementStatus.PROCESSING,
        background=background or settings.IMAGE_ENHANCEMENT_BACKGROUND,
    )
    attempt = ImageEnhancementJob.objects.filter(
        seller=request.user, background=job.background
    ).count()

    try:
        outcome = run_enhancement(
            upload=upload,
            job_id=str(job.id),
            attempt=attempt,
            background=background or None,
            product_category=product_category,
        )
    except ImageValidationError as exc:
        logger.info('Rejected upload for job %s: %s (%s)', job.id, exc.code, exc.detail)
        job.delete()
        return _error(exc.code, exc.message)
    except EnhancementError as exc:
        logger.warning('Enhancement %s failed: %s (%s)', job.id, exc.code, exc.detail)
        job.mark_failed(exc.code, exc.message)
        return _error(exc.code, exc.message, status=422,
                      job_id=str(job.id), status_state=job.status)
    except Exception:
        logger.exception('Unexpected enhancement failure for job %s', job.id)
        job.mark_failed('server_error', 'Something went wrong. Please try again.')
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    job.original.name = outcome.original_name
    job.enhanced.name = outcome.enhanced_name
    job.stages = outcome.stages
    job.quality = outcome.quality
    job.provider = outcome.provider
    job.is_ai = outcome.is_ai
    job.advisor_notes = (outcome.advisor or {}).get('notes', '')[:240]
    job.status = EnhancementStatus.COMPLETED
    job.save()

    return JsonResponse({
        'success': True,
        'job': job.as_dict(),
        'duration_ms': outcome.duration_ms,
    }, status=201)


@csrf_protect
@require_POST
@login_required
def upload_photo(request):
    """Store the seller's photo as-is, without enhancing it.

    The studio lets a seller skip the enhancement step, but the photo still
    has to reach the server or ``publish`` has no bytes to attach and would
    quietly create a product with no image. This endpoint closes that gap: it
    writes the upload to the same draft storage as an enhanced run and hands
    back a job id that ``publish`` already understands. The job is COMPLETED
    with no enhanced artefact, so nothing downstream can mistake it for an
    enhancement result.
    """
    if not throttle_allows(
        'ai_image_upload', request,
        max_requests=getattr(settings, 'IMAGE_ENHANCEMENT_RATE_LIMIT', 6), window_seconds=60,
    ):
        return _error(
            'rate_limited',
            'Too many uploads at once. Please wait a minute and try again.',
            status=429,
        )

    upload = request.FILES.get('image')
    if upload is None:
        return _error('missing_file', 'Please choose a photo of your product.')

    # Same byte-level validation as the enhancement pipeline, so a renamed
    # script or a decompression bomb is refused here too.
    try:
        validated = validate_upload(
            upload,
            max_bytes=getattr(settings, 'IMAGE_ENHANCEMENT_MAX_BYTES', 25 * 1024 * 1024),
            max_pixels=getattr(settings, 'IMAGE_ENHANCEMENT_MAX_PIXELS', 40_000_000),
        )
    except ImageValidationError as exc:
        logger.info('Rejected upload: %s (%s)', exc.code, exc.detail)
        return _error(exc.code, exc.message)

    job = ImageEnhancementJob.objects.create(
        seller=request.user,
        status=EnhancementStatus.PROCESSING,
        background=getattr(settings, 'IMAGE_ENHANCEMENT_BACKGROUND', BACKGROUNDS[0]),
        selection=Selection.ORIGINAL,
    )

    upload.seek(0)
    raw = upload.read()
    try:
        job.original.name = store_original(raw, validated.format, str(job.id))
    except StorageError as exc:
        logger.warning('Could not store upload for job %s: %s', job.id, exc)
        job.mark_failed('storage_failed', 'We could not save your photo.')
        return _error('storage_failed', 'We could not save your photo.', status=500,
                      job_id=str(job.id))

    job.status = EnhancementStatus.COMPLETED
    job.provider = 'upload'
    job.is_ai = False
    job.stages = [{
        'key': 'stored',
        'label': 'Photo saved as uploaded',
        'detail': '%s image, %d x %d' % (validated.format, validated.width, validated.height),
        'duration_ms': 0,
    }]
    job.quality = {
        'width': validated.width,
        'height': validated.height,
        'format': validated.format,
        'byte_size': validated.byte_size,
    }
    job.save()

    return JsonResponse({'success': True, 'job': job.as_dict()}, status=201)


@require_GET
@login_required
def status(request, job_id):
    """Poll a job. Only meaningful for work that outlives the request."""
    job = _get_owned_job(request, job_id)
    return JsonResponse({'success': True, 'job': job.as_dict()})


@csrf_protect
@require_POST
@login_required
def select(request):
    """Record the seller's choice: use the enhanced image, or keep the original.

    This is a *draft* decision. It does not touch any Product, and the
    enhanced file is not published by this endpoint.
    """
    job_id = (request.POST.get('job_id') or '').strip()
    choice = (request.POST.get('selection') or '').strip().lower()

    if not job_id:
        return _error('missing_job', 'No enhancement was selected.')
    if choice not in Selection.values:
        return _error('bad_selection', 'That choice is not valid.')

    job = _get_owned_job(request, job_id)
    if not job.is_complete:
        return _error('not_complete', 'That enhancement is not finished yet.', status=409)
    if choice == Selection.ENHANCED and not job.has_enhanced:
        return _error('no_enhanced_image', 'There is no enhanced image to choose.', status=409)

    job.selection = choice
    job.save(update_fields=['selection', 'updated_at'])
    return JsonResponse({'success': True, 'job': job.as_dict()})


@require_GET
@login_required
def draft(request):
    """The seller's most recent draft, so a page reload does not lose it."""
    job = (
        ImageEnhancementJob.objects
        .filter(seller=request.user)
        .exclude(status=EnhancementStatus.FAILED)
        .first()
    )
    return JsonResponse({
        'success': True,
        'job': job.as_dict() if job else None,
    })


@require_GET
@login_required
def health(request):
    """Report what the deployment can actually do, without leaking secrets.

    Useful in support ("is background removal on for me?") and in staging,
    where a silent fallback to the demo provider is the thing most worth
    noticing.
    """
    from .services.providers import get_provider
    from .services.background_remover import ClassicalSegmenter, U2NetSegmenter
    from .services.speech_to_text import status as speech_status

    provider = get_provider()
    neural = U2NetSegmenter().is_available()
    return JsonResponse({
        'success': True,
        'provider': provider.name,
        'is_ai': provider.is_ai,
        'is_demo': provider.name == 'demo',
        'advisor_enabled': bool(
            getattr(settings, 'IMAGE_ENHANCEMENT_ADVISOR_ENABLED', False)
            and getattr(settings, 'AI_API_KEY', '')
        ),
        'neural_segmentation': neural,
        'classical_segmentation': ClassicalSegmenter().is_available(),
        'backgrounds': list(BACKGROUNDS),
        'speech': speech_status(),
    })


# =========================================================================
# Voice endpoints
# =========================================================================

@csrf_protect
@require_POST
@login_required
def transcribe(request):
    """Speech-to-text from a recorded clip.

    Accepts multipart with an 'audio' file (webm/opus from the browser, or
    wav/m4a/mp3/ogg). Dictation runs on the local Whisper model by default:
    free, offline, and unmetered. ``AI_VOICE_PROVIDER=openrouter`` routes to
    the paid gateway instead, for deployments with no local CPU to spare.
    """
    if not throttle_allows(
        'ai_transcribe', request,
        max_requests=getattr(settings, 'AI_VOICE_RATE_LIMIT', 30), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many transcription requests. Please wait.',
                      status=429)

    audio = request.FILES.get('audio')
    if audio is None:
        return _error('missing_audio', 'Please provide an audio file.')

    try:
        audio_bytes = audio.read()
    except Exception as exc:
        return _error('unreadable_audio', 'Could not read the audio file.',
                      detail=str(exc))

    language = (request.POST.get('language') or None)
    prompt = (request.POST.get('prompt') or None)
    provider = getattr(settings, 'AI_VOICE_PROVIDER', 'local')

    if provider == 'openrouter':
        try:
            result = transcribe_audio(audio_bytes, language=language, prompt=prompt)
        except VoiceTextError as exc:
            logger.info('Transcription failed for %s: %s (%s)', request.user,
                        exc.code, exc.detail)
            return _error(exc.code, exc.message, status=422)
        except Exception:
            logger.exception('Unexpected transcription failure for %s', request.user)
            return _error('server_error', 'Something went wrong. Please try again.',
                          status=500)
        return JsonResponse({
            'success': True, 'text': result['text'],
            'model': result['model'], 'provider': 'openrouter',
        })

    if provider != 'local':
        # "browser" (or anything else) means the client is expected to
        # transcribe on its own, so there is nothing for the server to do.
        return _error(
            'speech_unavailable',
            'Voice typing is not available on this server right now.', status=503)

    try:
        result = transcribe_speech(audio_bytes, language=language, prompt=prompt)
    except SpeechError as exc:
        logger.info('Local transcription failed for %s: %s (%s)', request.user,
                    exc.code, exc.detail)
        # 503 with a known code is the signal for the browser to fall back to
        # its own dictation, so a missing model never blocks the seller.
        return _error(exc.code, exc.message, status=exc.status)

    return JsonResponse({
        'success': True,
        'text': result['text'],
        'language': result['language'],
        'duration': result['duration'],
        'model': result['model'],
        'provider': result['provider'],
    })


@csrf_protect
@require_POST
@login_required
def synthesise(request):
    """Text-to-speech. Accepts JSON with 'text', optional 'voice', 'speed', 'format'."""
    if not throttle_allows(
        'ai_tts', request,
        max_requests=getattr(settings, 'AI_TTS_RATE_LIMIT', 20), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many synthesis requests. Please wait.',
                      status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')

    text = (data.get('text') or '').strip()
    if not text:
        return _error('empty_text', 'Please provide text to synthesise.')

    voice = data.get('voice', 'alloy')
    speed = float(data.get('speed', 1.0))
    fmt = data.get('format', 'mp3')

    try:
        result = text_to_speech(text, voice=voice, speed=speed, format=fmt)
    except VoiceTextError as exc:
        logger.info('TTS failed for %s: %s (%s)', request.user, exc.code, exc.detail)
        return _error(exc.code, exc.message, status=422)
    except Exception:
        logger.exception('Unexpected TTS failure for %s', request.user)
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    audio_bytes = result['audio']
    response = FileResponse(io.BytesIO(audio_bytes), content_type=f'audio/{fmt}')
    response['Content-Disposition'] = f'inline; filename="speech.{fmt}"'
    response['X-AI-Model'] = result['model']
    return response


# =========================================================================
# Text endpoints
# =========================================================================

@csrf_protect
@require_POST
@login_required
def complete(request):
    """General text completion. Accepts JSON with 'prompt', optional params."""
    if not throttle_allows(
        'ai_text', request,
        max_requests=getattr(settings, 'AI_TEXT_RATE_LIMIT', 60), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many completion requests. Please wait.',
                      status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')

    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return _error('empty_prompt', 'Please provide a prompt.')

    system_prompt = data.get('system_prompt')
    temperature = float(data.get('temperature', 0.7))
    max_tokens = int(data.get('max_tokens', 2000))
    response_format = data.get('response_format')

    try:
        result = text_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
    except VoiceTextError as exc:
        logger.info('Completion failed for %s: %s (%s)', request.user, exc.code, exc.detail)
        return _error(exc.code, exc.message, status=422)
    except Exception:
        logger.exception('Unexpected completion failure for %s', request.user)
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    return JsonResponse({'success': True, 'text': result['text'], 'model': result['model']})


@csrf_protect
@require_POST
@login_required
def product_description(request):
    """Generate product description from structured data."""
    if not throttle_allows(
        'ai_product_desc', request,
        max_requests=getattr(settings, 'AI_TEXT_RATE_LIMIT', 60), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many requests. Please wait.',
                      status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')

    # Expected keys: title, category, materials, dimensions, care_instructions, style, occasion, price_range
    if not data.get('title'):
        return _error('missing_title', 'Product title is required.')

    try:
        result = generate_product_description(data)
    except VoiceTextError as exc:
        logger.info('Description generation failed for %s: %s (%s)', request.user, exc.code, exc.detail)
        return _error(exc.code, exc.message, status=422)
    except Exception:
        logger.exception('Unexpected description failure for %s', request.user)
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    return JsonResponse({'success': True, 'description': result['text'], 'model': result['model']})


@csrf_protect
@require_POST
@login_required
def catalog(request):
    """Write the whole listing entry the AI Studio shows for review.

    Accepts JSON with ``seller_notes`` (what the seller dictated or typed),
    an optional working ``title``, the chosen ``category``/``subcategory``,
    and the listing ``language``. Returns the title, the description and the
    search keywords in one response, so the studio makes a single AI call per
    regeneration instead of three.
    """
    if not throttle_allows(
        'ai_product_catalog', request,
        max_requests=getattr(settings, 'AI_TEXT_RATE_LIMIT', 60), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many requests. Please wait.', status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')
    if not isinstance(data, dict):
        return _error('bad_json', 'Invalid JSON body.')

    # A title alone is enough to write from, but the seller's own words are
    # what the listing should actually be based on, so either seeds the call.
    seller_notes = (data.get('seller_notes') or '').strip()[:4000]
    title = (data.get('title') or '').strip()[:200]
    if not title and not seller_notes:
        return _error(
            'missing_title',
            'Describe your product in your own words first, then generate the listing.',
        )

    try:
        result = generate_product_catalog(data)
    except VoiceTextError as exc:
        logger.info('Catalog generation failed for %s: %s (%s)', request.user,
                    exc.code, exc.detail)
        return _error(exc.code, exc.message, status=422)
    except Exception:
        logger.exception('Unexpected catalog failure for %s', request.user)
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    # A reply that parsed to neither field is a model failure, not an empty
    # listing: the studio would show blank fields with no way to tell why.
    if not result['title'] and not result['description']:
        return _error('empty_response',
                      'The writing assistant did not return a usable listing. Please try again.',
                      status=422)

    return JsonResponse({
        'success': True,
        'title': result['title'],
        'description': result['description'],
        'keywords': result['keywords'],
        # .get(), not []: a fallback provider or an older service can answer
        # without a placement, and a missing key here would turn that into a
        # 500 on a call the seller is waiting on.
        'category': result.get('category', ''),
        'subcategory': result.get('subcategory', ''),
        'model': result['model'],
    })


@csrf_protect
@require_POST
@login_required
def product_keywords(request):
    """Extract SEO keywords from product data."""
    if not throttle_allows(
        'ai_product_keywords', request,
        max_requests=getattr(settings, 'AI_TEXT_RATE_LIMIT', 60), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many requests. Please wait.',
                      status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')

    try:
        keywords = generate_seo_keywords(data)
    except VoiceTextError as exc:
        logger.info('Keywords failed for %s: %s (%s)', request.user, exc.code, exc.detail)
        return _error(exc.code, exc.message, status=422)
    except Exception:
        logger.exception('Unexpected keywords failure for %s', request.user)
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    return JsonResponse({'success': True, 'keywords': keywords})


@csrf_protect
@require_POST
@login_required
def product_tags(request):
    """Suggest marketplace tags from product data."""
    if not throttle_allows(
        'ai_product_tags', request,
        max_requests=getattr(settings, 'AI_TEXT_RATE_LIMIT', 60), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many requests. Please wait.',
                      status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')

    try:
        tags = generate_product_tags(data)
    except VoiceTextError as exc:
        logger.info('Tags failed for %s: %s (%s)', request.user, exc.code, exc.detail)
        return _error(exc.code, exc.message, status=422)
    except Exception:
        logger.exception('Unexpected tags failure for %s', request.user)
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    return JsonResponse({'success': True, 'tags': tags})


@csrf_protect
@require_POST
@login_required
def rewrite_seo(request):
    """Rewrite existing product copy for SEO without changing facts."""
    if not throttle_allows(
        'ai_rewrite_seo', request,
        max_requests=getattr(settings, 'AI_TEXT_RATE_LIMIT', 60), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many requests. Please wait.',
                      status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')

    text = (data.get('text') or '').strip()
    if not text:
        return _error('empty_text', 'Please provide text to rewrite.')

    product_data = data.get('product_data', {})

    try:
        result = rewrite_for_seo(text, product_data)
    except VoiceTextError as exc:
        logger.info('SEO rewrite failed for %s: %s (%s)', request.user, exc.code, exc.detail)
        return _error(exc.code, exc.message, status=422)
    except Exception:
        logger.exception('Unexpected rewrite failure for %s', request.user)
        return _error('server_error', 'Something went wrong. Please try again.', status=500)

    return JsonResponse({'success': True, 'text': result['text'], 'model': result['model']})




# =========================================================================
# Product publishing from AI Studio
# =========================================================================

def _unique_slug(model, base):
    """Return a slug for ``model`` that is not already taken.

    ``slug`` is unique on both Category and Product, so an AI draft that
    repeats a previous title must not blow up with an IntegrityError.
    """
    slug = slugify(base)[:190] or 'product'
    candidate, suffix = slug, 2
    while model.objects.filter(slug=candidate).exists():
        candidate = '%s-%d' % (slug, suffix)
        suffix += 1
    return candidate


@csrf_protect
@require_POST
@login_required
def publish(request):
    """Create a Product (as a draft listing) from the AI Studio wizard.

    Nothing here auto-publishes: the product is created ``available=False``
    so a seller can review it in the normal Django admin / product edit
    screen before it goes live.
    """
    # Imported here rather than at module scope to keep shop.models out of the
    # import graph of this module. It has to sit *above* the first use below:
    # a function-local import anywhere in the body makes Python treat the name
    # as local for the whole function, so calling it earlier raised
    # UnboundLocalError and every publish returned a 500.
    from shop.taxonomy import find_category, find_subcategory

    if not throttle_allows(
        'ai_publish', request,
        max_requests=getattr(settings, 'AI_TEXT_RATE_LIMIT', 60), window_seconds=60,
    ):
        return _error('rate_limited', 'Too many publish requests. Please wait.',
                      status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return _error('bad_json', 'Invalid JSON body.')
    if not isinstance(data, dict):
        return _error('bad_json', 'Invalid JSON body.')

    name = (data.get('title') or data.get('name') or '').strip()[:200]
    if not name:
        return _error('missing_title', 'Product title is required.')

    description = (data.get('description') or '').strip()
    if not description:
        return _error('missing_description', 'Product description is required.')
    # The description is AI output, i.e. untrusted input landing in a
    # RichTextField. Sanitize on the way in so a prompt-injected payload
    # cannot become stored XSS on the product page. bleach(strip=True) keeps
    # the text of a stripped tag, so also reject content that is now empty.
    description = sanitize_html(description)
    if not description.strip():
        return _error('missing_description', 'Product description is required.')

    category_name = (data.get('category') or '').strip()[:200]
    if not category_name:
        return _error('missing_category', 'Please choose a category.')

    # The category has to be one this shop already sells in. Creating one here
    # would turn a seller's typo (or a stale picker) into a new department in
    # the taxonomy, so an unknown name is reported back instead.
    category_obj = find_category(category_name)
    if category_obj is None:
        return _error(
            'unknown_category',
            'That category is not one we sell in. Please pick one from the list.',
        )

    subcategory_name = (data.get('subcategory') or '').strip()[:200]
    subcategory_obj = None
    if subcategory_name:
        subcategory_obj = find_subcategory(subcategory_name, category_obj)
        if subcategory_obj is None:
            return _error(
                'unknown_subcategory',
                'That subcategory does not belong to the chosen category.',
            )

    # Price arrives as a string/number from JSON; Decimal handles the exact
    # conversion and a bad value raises rather than silently storing 0.
    try:
        price = Decimal(str(data.get('price')).strip()).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        return _error('bad_price', 'Please enter a valid price.')
    if price <= 0:
        return _error('bad_price', 'Price must be greater than zero.')

    try:
        stock = max(0, int(data.get('stock') or 0))
    except (TypeError, ValueError):
        return _error('bad_stock', 'Stock must be a whole number.')

    from shop.models import Product, ProductImage

    seller_profile = getattr(request.user, 'sellerprofile', None)
    if seller_profile is None:
        return _error('no_seller_profile',
                      'Finish your seller profile before listing a product.',
                      status=409)

    # The enhancement draft must belong to this seller and be finished.
    job = None
    job_id = data.get('enhancement_job')
    if job_id:
        try:
            job = get_object_or_404(
                ImageEnhancementJob, pk=job_id, seller=request.user)
        except (ValueError, ValidationError):
            return _error('bad_job', 'That image job id is not valid.')
        if job.status != EnhancementStatus.COMPLETED:
            return _error('job_not_ready',
                          'That image is still being processed.', status=409)

    # ``use_enhanced`` may be overridden by the recorded selection, so the
    # seller's explicit pick on the compare step is the source of truth.
    use_enhanced = data.get('use_enhanced', True)
    if job is not None and job.selection == Selection.ORIGINAL:
        use_enhanced = False

    try:
        with transaction.atomic():
            product = Product.objects.create(
                name=name,
                slug=_unique_slug(Product, name),
                description=description,
                price=price,
                stock=stock,
                available=False,
                seller=seller_profile,
                category=category_obj,
                subcategory=subcategory_obj,
            )

            image_source = None
            if job is not None:
                if use_enhanced and job.has_enhanced:
                    image_source = job.enhanced
                elif job.original:
                    image_source = job.original

            if image_source is not None:
                chosen = image_source.name.rsplit('/', 1)[-1]
                # Copy the bytes into the product's own storage key rather
                # than pointing at the AI draft, so later draft cleanup can
                # never orphan a live product image.
                with default_storage.open(image_source.name) as src:
                    product.image.save(chosen, File(src), save=False)
                product.save(update_fields=['image'])
                ProductImage.objects.create(
                    product=product, image=product.image, is_main=True,
                    alt_text=name[:200],
                )

    except ValidationError as exc:
        logger.info('Publish rejected for %s: %s', request.user, exc.messages)
        return _error('invalid_product', '; '.join(exc.messages)[:300])
    except Exception:
        logger.exception('Product creation failed for %s', request.user)
        return _error('server_error', 'Could not create product. Please try again.',
                      status=500)

    logger.info('AI Studio draft published by %s as product %s',
                request.user, product.pk)
    return JsonResponse({
        'success': True,
        'product_id': product.pk,
        'product_url': product.get_absolute_url(),
        'available': product.available,
    }, status=201)
