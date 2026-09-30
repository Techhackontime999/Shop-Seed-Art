"""Voice and text AI services.

Thin orchestration over the OpenRouter client: validates inputs, applies
rate limiting, and returns clean, typed results. Nothing here touches the
image enhancement pipeline.
"""

import json
import logging
import re

from django.conf import settings

from ..clients.openrouter import OpenRouterClient
from ..services.image_enhancer import EnhancementError

logger = logging.getLogger(__name__)


class VoiceTextError(EnhancementError):
    """A voice/text operation failed. Same seller-safe contract as image errors."""
    pass


def _check_voice_key() -> None:
    if not getattr(settings, 'AI_API_KEY', ''):
        raise VoiceTextError('not_configured', 'Voice AI is not configured.')


def _check_text_key() -> None:
    if not getattr(settings, 'AI_API_KEY', ''):
        raise VoiceTextError('not_configured', 'Text AI is not configured.')


def _client() -> OpenRouterClient:
    """Instantiate the OpenRouter client with current settings."""
    return OpenRouterClient(
        timeout=getattr(settings, 'AI_TIMEOUT', 20),
        max_retries=getattr(settings, 'AI_MAX_RETRIES', 2),
    )


def transcribe_audio(audio_bytes: bytes, *,
                     language: str = None,
                     prompt: str = None) -> dict:
    """Speech-to-text. Returns ``{'text': str, 'model': str}``.

    Raises :class:`VoiceTextError` with a seller-safe code/message on failure.
    """
    _check_voice_key()
    if not audio_bytes:
        raise VoiceTextError('empty_audio', 'No audio provided.')

    try:
        client = _client()
        result = client.transcribe_audio(
            audio_bytes,
            language=language,
            prompt=prompt,
            timeout=getattr(settings, 'AI_VOICE_TIMEOUT', 30),
        )
    except Exception as exc:
        logger.exception('Transcription failed')
        raise VoiceTextError(
            'transcription_failed', 'We could not transcribe that audio.',
            detail=str(exc),
        ) from exc

    if not result.success:
        raise VoiceTextError(
            result.code or 'transcription_failed',
            result.error or 'Transcription failed.',
            detail=result.error,
        )

    return {
        'text': result.data.get('content', ''),
        'model': result.data.get('model', ''),
    }


def text_to_speech(text: str, *,
                   voice: str = 'alloy',
                   speed: float = 1.0,
                   format: str = 'mp3') -> dict:
    """Text-to-speech. Returns ``{'audio': bytes, 'model': str, 'format': str}``.

    Raises :class:`VoiceTextError` with a seller-safe code/message on failure.
    """
    _check_voice_key()
    if not text or not text.strip():
        raise VoiceTextError('empty_text', 'No text to synthesise.')

    try:
        client = _client()
        result = client.text_to_speech(
            text,
            voice=voice,
            speed=speed,
            response_format=format,
            timeout=getattr(settings, 'AI_TTS_TIMEOUT', 30),
        )
    except Exception as exc:
        logger.exception('TTS failed')
        raise VoiceTextError(
            'tts_failed', 'We could not synthesise that speech.',
            detail=str(exc),
        ) from exc

    if not result.success:
        raise VoiceTextError(
            result.code or 'tts_failed',
            result.error or 'Speech synthesis failed.',
            detail=result.error,
        )

    return {
        'audio': result.raw_content,
        'model': result.data.get('model', ''),
        'format': format,
    }


# The provider's own wording ("The AI service is rate limiting us.") is
# written for a developer, not a seller, so each upstream failure code is
# translated once here. The provider message is kept in ``detail`` for the
# logs and never reaches the browser.
_SELLER_MESSAGES = {
    'rate_limited': 'The writing assistant is busy right now. Please try again in a minute.',
    'out_of_credit': 'The writing assistant is unavailable right now. Please try again shortly.',
    'model_unavailable': 'The writing assistant is unavailable right now. Please try again shortly.',
    'server_error': 'The writing assistant is unavailable right now. Please try again shortly.',
    'timeout': 'The writing assistant took too long to answer. Please try again.',
    'empty_response': 'The writing assistant did not return a usable answer. Please try again.',
    'auth_error': 'The writing assistant is not configured correctly. Please contact support.',
    'not_configured': 'The writing assistant is not available. Please contact support.',
}


def _seller_message(code: str, fallback: str) -> str:
    return _SELLER_MESSAGES.get(code or '', fallback)


def text_completion(prompt: str, *,
                    system_prompt: str = None,
                    temperature: float = 0.7,
                    max_tokens: int = 2000,
                    response_format: dict = None) -> dict:
    """General text completion. Returns ``{'text': str, 'model': str}``.

    Raises :class:`VoiceTextError` with a seller-safe code/message on failure.
    """
    _check_text_key()
    if not prompt or not prompt.strip():
        raise VoiceTextError('empty_prompt', 'Please enter a description first.')

    try:
        client = _client()
        result = client.text_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            timeout=getattr(settings, 'AI_TEXT_TIMEOUT', 30),
        )
    except Exception as exc:
        logger.exception('Text completion failed')
        raise VoiceTextError(
            'completion_failed', 'We could not complete that request.',
            detail=str(exc),
        ) from exc

    if not result.success:
        code = result.code or 'completion_failed'
        raise VoiceTextError(
            code,
            _seller_message(code, 'We could not write that just now. Please try again.'),
            detail=result.error,
        )

    return {
        'text': result.data.get('content', ''),
        'model': result.data.get('model', ''),
    }


# --- Specialised text helpers for ecommerce ----------------------------------

PRODUCT_DESCRIPTION_SYSTEM = (
    'You write concise, honest product descriptions for an artisan marketplace. '
    'Never invent details the seller did not provide. Use natural language, '
    'include key specs (material, size, care), and keep it under 200 words. '
    'Do not use marketing fluff, superlatives, or unverifiable claims. '
    'Reply with plain prose only: no markdown, no bullet points, no headings.'
)

SEO_KEYWORDS_SYSTEM = (
    'You extract 8-12 relevant search keywords for an artisan product listing. '
    'Reply with JSON only, in the form {"keywords": ["one", "two"]}. '
    'Use lowercase phrases. No prose, no markdown, no category names.'
)

PRODUCT_TAGS_SYSTEM = (
    'You suggest 5-8 relevant tags for an artisan marketplace listing. '
    'Reply with JSON only, in the form {"tags": ["one", "two"]}. '
    'Use single lowercase words or short phrases. No prose, no markdown.'
)

def generate_product_description(product_data: dict) -> dict:
    """Generate a product description from structured product data.

    ``product_data`` should contain keys like: title, category, materials,
    dimensions, care_instructions, style, occasion, price_range.

    Prose only. The AI Studio uses :func:`generate_product_catalog` instead,
    because a listing also needs a title and this deliberately does not
    invent one.
    """
    prompt = 'Write a product description for:\n' + _fact_lines(product_data)
    result = text_completion(
        prompt,
        system_prompt=PRODUCT_DESCRIPTION_SYSTEM,
        temperature=0.5,
        max_tokens=400,
    )
    result['text'] = strip_markdown(result['text'])
    return result


# --- The studio's single "write my listing" call ---------------------------
#
# The studio needs a title, a description and search terms from one seller
# sentence. Asking for them in three separate calls triples the latency and,
# on the free tier this project runs against, triples the chance that the
# seller watches two spinners and an error instead of a listing. One JSON
# reply keeps it to a single round trip.

PRODUCT_CATALOG_SYSTEM = (
    'You write the listing copy for a product on an artisan marketplace.\n'
    'You use only the facts you are given. You never invent a material, a '
    'technique, a size, an origin or a use that the seller did not mention.\n'
    'Reply with JSON only, in exactly this shape:\n'
    '{"title": "...", "description": "...", "keywords": ["...", "..."]}\n'
    'The title must be one short line of at most 70 characters, in plain '
    'words, with no quotes, no markdown and no price.\n'
    'The description must be 2 to 4 sentences of plain prose under 120 words, '
    'with no markdown, no bullet points, no headings and no emoji.\n'
    'Give 6 to 10 search keywords as short lowercase phrases. Never repeat a '
    'word from the title as a keyword.'
)

# Human labels for the fact keys. A raw "seller_notes: ..." in the prompt
# reads like a database column to the model, and the seller's own words are
# the single most important input, so it gets a label that says so.
_FACT_LABELS = {
    'title': 'Working title',
    'seller_notes': "The seller's own description of the product",
    'category': 'Category',
    'subcategory': 'Subcategory',
    'materials': 'Materials',
    'dimensions': 'Dimensions',
    'care_instructions': 'Care instructions',
    'style': 'Style',
    'occasion': 'Occasion',
    'price_range': 'Price the seller is considering',
}

# The studio offers exactly these two. An unrecognised code falls back to
# English rather than being passed through, because the value ends up in an
# instruction to the model.
_LANGUAGE_NAMES = {
    'en': 'English',
    'hi': 'Hindi, written in the Devanagari script',
}

# Keys that steer the prompt rather than describe the product, so they are
# never echoed to the model as a fact.
_PROMPT_CONTROL_KEYS = ('language',)


def _fact_lines(product_data: dict) -> str:
    """Render the product facts as a ``label: value`` block for the prompt."""
    return '\n'.join(
        '%s: %s' % (_FACT_LABELS.get(key, key), value)
        for key, value in product_data.items()
        if value and key not in _PROMPT_CONTROL_KEYS
    )


def _language_clause(language) -> str:
    """The instruction that actually makes the model switch language.

    Passing ``language: hi`` as a fact is not enough: the model treats it as
    metadata and answers in English anyway. It has to be an instruction.
    """
    name = _LANGUAGE_NAMES.get(str(language or 'en').strip().lower())
    if not name:
        return ''
    return (
        '\nWrite the title, the description and the keywords in %s. If the '
        "seller's notes are in another language, translate the facts, do not "
        'translate proper nouns such as place names or artisan names.' % name
    )


def _clean_title(value) -> str:
    """Normalise a model-supplied title to one clean line of plain words."""
    title = strip_markdown(str(value or '').strip())
    title = re.sub(r'^[\s"\'“‘”‘’`*\-–—]+', '', title)
    # Trailing sentence punctuation goes too: a title lifted out of a prose
    # sentence would otherwise be listed as "Handwoven Runner." on the
    # storefront.
    title = re.sub(r'[\s"\'“”‘’`*.!?,;:]+$', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    if len(title) <= 70:
        return title
    # Cut on a word boundary so the title never ends mid-word.
    clipped = title[:70]
    cut = clipped.rsplit(' ', 1)[0].rstrip(' ,;:-')
    return cut or clipped


def _parse_catalog(raw_text) -> tuple:
    """Pull ``(title, description)`` out of a catalog reply.

    Lenient in the same way as :func:`_parse_string_list`, because a real
    model will fence the JSON, answer in prose, or be cut off mid-document.
    A title is the one field the studio cannot publish without, so a reply
    that is not parseable as JSON still yields one rather than failing the
    whole listing.
    """
    if not isinstance(raw_text, str):
        return '', ''
    text = raw_text.strip()
    fence = re.match(r'^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```$', text, re.S)
    if fence:
        text = fence.group(1).strip()

    for candidate in (text, _repair_truncated_json(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        title = _clean_title(data.get('title'))
        description = _clean_prose(data.get('description'))
        if title or description:
            return title, description

    # Not JSON at all. A prose answer already has the right shape: an opening
    # line that names the product, and the paragraphs that follow it.
    return _catalog_from_prose(text)


def _catalog_from_prose(text) -> tuple:
    """Derive a title and description from a reply that was not JSON."""
    if not text:
        return '', ''
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return '', ''
    body = ' '.join(lines)
    head = lines[0]
    # The title is the opening *sentence* whenever the reply begins with one.
    # A single-line prose answer ("Handwoven Runner. A soft runner woven…")
    # has no line break to split on, and a length test alone would put that
    # entire sentence-pair into the title field. With no sentence break to
    # split on, _clean_title clips the line to something readable anyway.
    if re.search(r'[.!?]\s', head):
        head = re.split(r'(?<=[.!?])\s', head)[0]
    return _clean_title(head), _clean_prose(body)


def _clean_prose(value) -> str:
    return strip_markdown(str(value or '').strip())


def generate_product_catalog(product_data: dict) -> dict:
    """Write a whole listing entry: title, description, search terms, place.

    Returns ``{'title', 'description', 'keywords', 'category', 'subcategory',
    'model'}``. ``product_data`` may carry ``seller_notes`` (the seller's
    dictated or typed words) and ``language``; both steer the prompt rather
    than being treated as facts.

    The placement is only ever a real row of the shop's taxonomy. The model is
    asked to pick from the exact names it is given, and the answer is then
    resolved through :mod:`shop.taxonomy`, so a hallucinated department cannot
    reach the database.
    """
    from shop.taxonomy import (category_choices, find_category,
                               find_subcategory, suggest_category,
                               suggest_subcategory)

    taxonomy = category_choices()

    system_prompt = PRODUCT_CATALOG_SYSTEM + _language_clause(
        product_data.get('language')
    ) + _taxonomy_clause(taxonomy)

    prompt = 'Write the listing copy for this product:\n' + _fact_lines(product_data)
    if taxonomy:
        prompt += (
            '\nAlso give the "category" and "subcategory" keys, using the '
            'departments and subcategories listed in your instructions.'
        )

    result = text_completion(
        prompt,
        system_prompt=system_prompt,
        temperature=0.5,
        # Room for a title, 120 words of prose, ten keywords and the two
        # placement names, and still small enough that the free tier answers
        # in one go.
        max_tokens=700,
    )

    title, description = _parse_catalog(result['text'])
    keywords = _parse_string_list(
        _catalog_keywords_blob(result['text']), 'keywords', limit=10
    )
    # A listing with no title cannot be published, so a reply that yielded
    # prose only still gets one, lifted from the description.
    if not title and description:
        title = _clean_title(re.split(r'(?<=[.!?])\s', description)[0])

    category_name, subcategory_name = _parse_catalog_placement(result['text'])

    # What the seller already chose wins over the model's guess: they looked at
    # the list, the model did not.
    chosen_category = find_category(product_data.get('category'))
    if chosen_category is None:
        chosen_category = find_category(category_name)

    if chosen_category is None:
        # No usable answer from the model either, so guess from the words. The
        # studio shows this in a picker the seller confirms, so a rough guess
        # is a convenience rather than a decision.
        chosen_category = suggest_category(
            '%s %s' % (title, product_data.get('seller_notes') or ''),
            default=_first_category(),
        )

    chosen_subcategory = None
    if chosen_category is not None:
        chosen_subcategory = find_subcategory(
            product_data.get('subcategory') or subcategory_name, chosen_category)
        if chosen_subcategory is None:
            chosen_subcategory = suggest_subcategory(
                '%s %s' % (title, description[:200]), chosen_category)

    return {
        'title': title,
        'description': description,
        'keywords': keywords,
        'category': chosen_category.name if chosen_category else '',
        'subcategory': chosen_subcategory.name if chosen_subcategory else '',
        'model': result['model'],
    }


def _first_category():
    from shop.models import Category

    return Category.objects.order_by('name').first()


def _taxonomy_lines(taxonomy):
    lines = []
    for entry in taxonomy:
        subs = ', '.join(sub['name'] for sub in entry['subcategories'])
        lines.append('- %s%s' % (entry['name'], (' > %s' % subs) if subs else ''))
    return '\n'.join(lines)


def _taxonomy_clause(taxonomy):
    """The allowed placement, as a rule.

    The list sits in the system prompt rather than with the seller's facts.
    The allowed names are a constraint on the answer, not something the model
    should treat as a fact to echo, and a long description cannot push them
    out of sight.
    """
    if not taxonomy:
        return ''
    return (
        '\nYou also choose where the product belongs in this shop\'s taxonomy. '
        'Reply with exactly two extra keys, "category" and "subcategory", each '
        'copied verbatim from this list, with the subcategory taken from the '
        'line of its own category. Never invent a department or a subcategory '
        'that is not on the list, and leave "subcategory" as an empty string '
        'when none of them fit.\n'
        '\nThe shop sells in these departments:\n'
        + _taxonomy_lines(taxonomy)
    )


def _parse_catalog_placement(raw_text):
    """Pull "category" and "subcategory" out of a reply.

    Models wander: the keys can arrive in any order, be nested in a
    "placement" object, or arrive as prose ("Category: Paintings & Wall Art").
    All three shapes are read here so a usable answer is not thrown away over
    punctuation.
    """
    if not isinstance(raw_text, str):
        return '', ''

    # A nested object is the shape the reply is asked for, so try it first.
    match = re.search(r'"placement"\s*:\s*\{(.*?)\}', raw_text, re.S)
    blob = match.group(1) if match else raw_text

    found = {}
    for key in ('category', 'subcategory'):
        hit = re.search(r'"%s"\s*:\s*"([^"]{1,200})"' % key, blob, re.I)
        if hit:
            found[key] = hit.group(1).strip()
    if found:
        return found.get('category', ''), found.get('subcategory', '')

    category = ''
    subcategory = ''
    for line in blob.splitlines():
        # "**Category:** Paintings & Wall Art" and "Category - Paintings" both
        # happen in practice.
        labelled = re.match(
            r'\s*[*#>\-\s]*([A-Za-z ]{3,20})\s*[*:#>\-]{1,2}\s*(.+)', line)
        if not labelled:
            continue
        key = labelled.group(1).strip().casefold()
        # "**Category:** Books" leaves the space after the colon inside the
        # captured value, and a trailing period rides along on prose lines, so
        # both ends get cleaned rather than trusted.
        value = labelled.group(2).strip(' \t*`":').rstrip('. ').strip(' \t*`":')
        if not value or len(value) > 200:
            continue
        if key == 'category' and not category:
            category = value
        elif key in ('subcategory', 'sub category') and not subcategory:
            subcategory = value
    return category, subcategory


def _catalog_keywords_blob(raw_text) -> str:
    """Isolate the keywords array so the list parser can read it on its own.

    ``_parse_string_list`` only understands a whole document, and a title and
    a description wrapped around the keywords would make it fall through to
    its prose split. Handing it just the array keeps the repair and
    clean-up behaviour that the keywords endpoint already relies on.
    """
    if not isinstance(raw_text, str):
        return ''
    match = re.search(r'"keywords"\s*:\s*\[(.*?)\]', raw_text, re.S)
    if match:
        return '[%s]' % match.group(1)
    # No JSON to find: the list parser's own prose split is the best guess.
    return raw_text


def strip_markdown(text: str) -> str:
    """Remove markdown decoration from prose that is rendered as plain text.

    Descriptions end up in the product description field and in the studio
    textarea, so ``**bold**`` and ``- bullets`` would be shown to shoppers
    literally. Only decoration is removed; the wording, and any sentence
    structure the model used, is left exactly as written.
    """
    if not text:
        return ''
    cleaned = re.sub(r'```[a-zA-Z0-9_-]*\n?|```', '', text)
    cleaned = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', cleaned)   # headings
    cleaned = re.sub(r'(?m)^\s*[-*+]\s+', '', cleaned)         # bullets
    cleaned = cleaned.replace('**', '').replace('__', '')
    # Single-marker emphasis, but only when the marker is not inside a word:
    # seller copy is full of names like machine_wash or size_40, and eating
    # those underscores would corrupt the specification.
    cleaned = re.sub(r'(?<![\w*])\*(?=\S)(.+?\S)\*(?!\w)', r'\1', cleaned, flags=re.S)
    cleaned = re.sub(r'(?<![\w_])_(?=\S)(.+?\S)_(?![\w_])', r'\1', cleaned, flags=re.S)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def _parse_string_list(raw_text: str, key: str, limit: int = 12) -> list:
    """Pull a list of lowercase strings out of a model's JSON reply.

    The model is asked for ``{"keywords": [...]}``, but a real model will
    often wrap that in a ```json fence or emit a bare array, and a truncated
    reply is normal on a small token budget. A truncated JSON document is
    repaired by closing its unterminated string/array/object, which recovers
    the complete items instead of discarding the whole reply.
    """
    # Guarded because this is the boundary between a provider reply and the
    # rest of the app: anything non-string yields no keywords rather than a
    # TypeError in the middle of a seller's request.
    if not isinstance(raw_text, str):
        return []
    text = raw_text.strip()
    # Strip a markdown code fence, with or without a language tag.
    fence = re.match(r'^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```$', text, re.S)
    if fence:
        text = fence.group(1).strip()

    for candidate in (text, _repair_truncated_json(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get(key), list):
            values = data[key]
        elif isinstance(data, list):
            values = data
        else:
            continue
        cleaned = [_clean_term(v) for v in values]
        return [v for v in cleaned if v][:limit]

    # Last resort: split on the separators and keep anything word-like. This
    # is what stops a malformed reply becoming fragments like '": "handwove'.
    # Only fall back to a prose split when the reply was never JSON at all.
    # Splitting a malformed JSON document would yield fragments like
    # 'a":[1', which is worse than returning nothing.
    if not re.match(r'^\s*[\[{]', text):
        cleaned = (_clean_term(part) for part in re.split(r'[,\n]', text))
        return [v for v in cleaned if _looks_like_term(v)][:limit]
    return []


def _looks_like_term(value: str) -> bool:
    """Reject JSON leftovers such as ``keywords`` or a bare ``{``."""
    if not value or len(value) > 60:
        return False
    return bool(re.search(r'[a-z]', value))


def _repair_truncated_json(text: str) -> str:
    """Close a JSON document that was cut off mid-generation.

    Only repairs the *closing* punctuation: strings are closed and open
    arrays/objects are closed. It never invents or reorders content, so the
    result can only ever contain items the model actually emitted.
    """
    if not text or not text.lstrip().startswith(('{', '[')):
        return ''

    stack, in_string, escaped = [], False, False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '[{':
            stack.append(char)
        elif char in ']}':
            # An unbalanced closer means the document is malformed beyond a
            # simple cut-off, so give up rather than emit nonsense.
            if not stack or {'[': ']', '{': '}'}[stack[-1]] != char:
                return ''
            stack.pop()

    repaired = text
    if in_string:
        repaired += '"'
    # A dangling comma before a closing bracket is invalid JSON.
    while re.search(r',\s*$', repaired):
        repaired = re.sub(r',\s*$', '', repaired)
    repaired += ''.join(']' if c == '[' else '}' for c in reversed(stack))
    return repaired if repaired != text else ''


def _clean_term(value) -> str:
    """Normalise one keyword/tag to a bare lowercase phrase."""
    text = str(value or '')
    # Drop surrounding quotes/braces and any JSON key prefix.
    text = re.sub(r'^[\s"\'\[{,:]+', '', text)
    text = re.sub(r'[\s"\'\]\},:]+$', '', text)
    return text.strip().lower()


def generate_seo_keywords(product_data: dict) -> list:
    """Extract SEO keywords from product data."""
    prompt = 'Extract keywords for:\n' + _fact_lines(product_data)
    # No ``response_format``: several free-tier models reject it with a 400
    # ("Provider returned error"), and the system prompt already specifies
    # the JSON shape. ``_parse_string_list`` copes with a plain or fenced
    # reply, so the lenient path is both simpler and more portable.
    result = text_completion(
        prompt,
        system_prompt=SEO_KEYWORDS_SYSTEM,
        temperature=0.3,
        max_tokens=400,
    )
    return _parse_string_list(result['text'], 'keywords')


def generate_product_tags(product_data: dict) -> list:
    """Suggest marketplace tags from product data."""
    prompt = 'Suggest tags for:\n' + _fact_lines(product_data)
    # See generate_seo_keywords: response_format is not portable across the
    # free tier, so the prompt is the contract.
    result = text_completion(
        prompt,
        system_prompt=PRODUCT_TAGS_SYSTEM,
        temperature=0.3,
        max_tokens=400,
    )
    return _parse_string_list(result['text'], 'tags')


def rewrite_for_seo(existing_text: str, product_data: dict) -> dict:
    """Rewrite existing product copy for better SEO without changing facts."""
    prompt = (
        'Rewrite this product description for better search visibility. '
        'Keep all facts identical. Do not add or remove details.\n\n'
        f'Current: {existing_text}\n\n'
        f'Product context: {product_data}'
    )
    return text_completion(
        prompt,
        system_prompt=(
            'You are an SEO copywriter for artisan products. Rewrite for clarity '
            'and keyword coverage without changing any facts. Return only the '
            'rewritten description.'
        ),
        temperature=0.4,
        max_tokens=500,
    )