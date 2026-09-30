"""OpenRouter chat-completions client.

What OpenRouter is: a single HTTP gateway in front of many hosted models,
speaking the OpenAI chat-completions shape. What it is **not**: an image
editor. It accepts image *inputs* for vision analysis and returns *text*. It
cannot return edited pixels.

So this client is used for the voice and text features. It is deliberately
never given the ability to alter an image, and the image enhancement pipeline
makes no external call at all.

Why that matters for this codebase specifically: a generative model asked to
"improve" an artisan's painting or saree will happily repaint the pattern,
garble printed text and shift the dyed colour. Those are the product rules
forbidden, and the architecture makes the failure unreachable rather than
merely discouraged — ``services/image_processor.py`` is pure Pillow/NumPy and
contains no network client.

The ``describe_image`` / ``image_guidance`` methods below exist for the
optional vision advisor, which is **off by default**
(``IMAGE_ENHANCEMENT_ADVISOR=none``) and is not part of the normal image
path. They are retained because a future "describe this product for my
listing" feature needs exactly this, and because leaving the capability
present but unused is more honest than pretending the gateway cannot do it.

Credentials are read from settings (populated from the environment) and are
never sent to, or reachable from, the browser.
"""

import base64
import logging
import time
from typing import Optional, List

import requests
from django.conf import settings

from .base import AIAPIClient, AIResponse

logger = logging.getLogger(__name__)

_CHAT_PATH = '/chat/completions'

# Sent so OpenRouter can attribute usage to this deployment. Neither value is
# a secret.
_REFERER_HEADER = 'X-Title'
_REFERER_URL = 'HTTP-Referer'

# Failure codes that mean "this particular model could not serve the request".
# A different model might, so the caller is allowed to try the next candidate.
# Deliberately excludes ``auth_error`` (a bad key fails for every model) and
# ``not_configured`` (retrying cannot invent a setting).
_MODEL_UNAVAILABLE_CODES = frozenset({
    'rate_limited', 'server_error', 'empty_response', 'model_unavailable',
    'out_of_credit',
})


def _is_model_unavailable(response) -> bool:
    """True when trying another model is worth the latency."""
    if response is None or response.success:
        return False
    return response.code in _MODEL_UNAVAILABLE_CODES


def _extract_content(message: dict) -> str:
    """Return usable assistant text from a chat completion message.

    Some models (notably reasoning-tuned ones on the free tier) can spend the
    entire ``max_tokens`` budget on hidden reasoning and return
    ``content: None``. Falling back to the reasoning text would silently ship
    chain-of-thought to sellers, so an empty result is returned as empty and
    the caller treats it as a model-level failure.
    """
    content = message.get('content')
    if isinstance(content, list):
        # Some providers return content as a list of parts.
        content = ''.join(
            part.get('text', '') for part in content
            if isinstance(part, dict)
        )
    if not isinstance(content, str):
        return ''
    return content.strip()


class OpenRouterClient(AIAPIClient):
    """Chat + vision access through OpenRouter."""

    def __init__(self, *, model=None, vision_model=None, **kwargs):
        super().__init__(**kwargs)
        self.model = model or self._setting('AI_MODEL', '')
        self.vision_model = vision_model or self._setting('AI_VISION_MODEL', '') or self.model

    @staticmethod
    def _setting(name, default):
        from django.conf import settings

        return getattr(settings, name, default)

    def _request(self, endpoint: str, payload: dict, expect_raw: bool = False):
        url = self.base_url + endpoint
        headers = {
            'Authorization': 'Bearer %s' % self.api_key,
            'Content-Type': 'application/json',
            _REFERER_HEADER: 'Shop-Seed Art',
            _REFERER_URL: self._setting('SITE_URL', 'http://localhost:8000'),
        }
        response = self.session.post(
            url, headers=headers, json=payload, timeout=self.timeout
        )
        if expect_raw:
            return response.status_code, response.content
        try:
            data = response.json()
        except ValueError:
            data = {'error': {'message': response.text[:200]}}
        return response.status_code, data

    def chat_completion(self, messages, *, model=None, temperature=0.2,
                        max_tokens=1200, response_format=None):
        payload = {
            'model': model or self.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if response_format:
            payload['response_format'] = response_format

        result = self.execute(endpoint=_CHAT_PATH, payload=payload, use_cache=True)
        if not result.success:
            return result

        choices = (result.data or {}).get('choices') or []
        if not choices:
            return AIResponseFactory.failure('empty_response', 'The AI service returned nothing.')
        message = choices[0].get('message') or {}
        return AIResponseFactory.success(
            content=message.get('content') or '',
            model=(result.data or {}).get('model', ''),
        )

    def describe_image(self, image_bytes: bytes, *, prompt: str, schema_hint: str = '',
                       model: Optional[str] = None) -> AIResponse:
        """Send an image plus a prompt and return the model's text.

        The image travels as an inline ``data:`` URL, which OpenRouter accepts
        for vision models. The payload can be large, so this is never cached
        and always runs under the client timeout.
        """
        if not image_bytes:
            return AIResponseFactory.failure('empty_image', 'No image to analyse.')

        encoded = base64.b64encode(image_bytes).decode('ascii')
        content = [
            {'type': 'text', 'text': prompt if not schema_hint
                            else '%s\n\nRespond with JSON matching:\n%s' % (prompt, schema_hint)},
            {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,%s' % encoded}},
        ]
        return self.chat_completion(
            [{'role': 'user', 'content': content}],
            model=model or self.vision_model,
            temperature=0.0,
            max_tokens=500,
            response_format={'type': 'json_object'},
        )

    def transcribe_audio(self, audio_bytes: bytes, *,
                         model: Optional[str] = None,
                         language: Optional[str] = None,
                         prompt: Optional[str] = None,
                         timeout: Optional[float] = None) -> AIResponse:
        """Speech-to-text via OpenRouter's Whisper-compatible endpoint.

        Returns the transcribed text. Any failure returns an error response;
        the caller decides how to handle it.
        """
        if not audio_bytes:
            return AIResponseFactory.failure('empty_audio', 'No audio to transcribe.')

        previous = self.timeout
        if timeout is not None:
            self.timeout = timeout

        try:
            encoded = base64.b64encode(audio_bytes).decode('ascii')
            payload = {
                'model': model or self._setting('AI_VOICE_MODEL', ''),
                'file': f'data:audio/webm;base64,{encoded}',
            }
            if language:
                payload['language'] = language
            if prompt:
                payload['prompt'] = prompt

            result = self.execute(
                endpoint='/audio/transcriptions',
                payload=payload,
                use_cache=False,
            )
        finally:
            self.timeout = previous

        if not result.success:
            return result

        data = result.data or {}
        text = data.get('text') or data.get('transcription') or ''
        return AIResponseFactory.success(content=text, model=data.get('model', ''))

    def text_to_speech(self, text: str, *,
                       model: Optional[str] = None,
                       voice: str = 'alloy',
                       speed: float = 1.0,
                       response_format: str = 'mp3',
                       timeout: Optional[float] = None) -> AIResponse:
        """Text-to-speech via OpenRouter's TTS endpoint.

        Returns audio bytes. The voice options depend on the model (OpenAI-compatible):
        alloy, echo, fable, onyx, nova, shimmer.
        """
        if not text or not text.strip():
            return AIResponseFactory.failure('empty_text', 'No text to synthesise.')

        previous = self.timeout
        if timeout is not None:
            self.timeout = timeout

        try:
            payload = {
                'model': model or self._setting('AI_TTS_MODEL', ''),
                'input': text[:4096],  # OpenAI TTS limit
                'voice': voice,
                'speed': max(0.25, min(4.0, speed)),
                'response_format': response_format,
            }
            result = self.execute(
                endpoint='/audio/speech',
                payload=payload,
                use_cache=False,
                expect_raw=True,
            )
        finally:
            self.timeout = previous

        if not result.success:
            return result

        # For TTS, the response is binary audio, not JSON
        # The base client's execute() expects JSON, so we handle this specially
        return AIResponseFactory.success(
            content=result.raw_content,
            model=result.data.get('model', '') if isinstance(result.data, dict) else '',
        )

    def _text_model_candidates(self, model: Optional[str]) -> list:
        """Ordered model ids to try for a text call.

        The primary model comes first, then anything in
        ``AI_TEXT_FALLBACK_MODELS``. This exists because OpenRouter's free
        (``:free``) tier is dynamic: a model that worked yesterday can return
        404 "no endpoints found" or be 429'd today, which is a provider
        availability problem rather than a bug in the call.
        """
        primary = model or self._setting('AI_TEXT_MODEL', '')
        candidates = [primary] if primary else []

        raw = self._setting('AI_TEXT_FALLBACK_MODELS', '')
        for extra in (part.strip() for part in str(raw).split(',')):
            # Never retry the primary: a second identical attempt just burns
            # the rate limit faster.
            if extra and extra not in candidates:
                candidates.append(extra)
        return candidates

    def text_completion(self, prompt: str, *,
                        model: Optional[str] = None,
                        temperature: float = 0.7,
                        max_tokens: int = 2000,
                        system_prompt: Optional[str] = None,
                        response_format: Optional[dict] = None,
                        timeout: Optional[float] = None) -> AIResponse:
        """General-purpose text completion via chat/completions.

        Tries each candidate model in turn and returns the first usable
        answer. ``model_used`` records which one actually served it so the
        caller (and the health endpoint) can report it.
        """
        if not prompt or not prompt.strip():
            return AIResponseFactory.failure('empty_prompt', 'No prompt provided.')

        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': prompt})

        candidates = self._text_model_candidates(model)
        if not candidates:
            return AIResponseFactory.failure(
                'not_configured', 'No text model is configured.')

        last: Optional[AIResponse] = None
        attempted = 0
        for index, candidate in enumerate(candidates):
            is_last = index == len(candidates) - 1
            attempted = index + 1
            response = self._complete_once(
                candidate, messages, temperature, max_tokens,
                response_format, timeout,
                # Only the final candidate earns a full retry budget; trying
                # every model three times would triple the latency of a
                # total outage.
                max_retries=self.max_retries if is_last else 0,
            )
            # Reasoning-tuned models bill reasoning against max_tokens, so a
            # budget that is fine for a normal model can be entirely consumed
            # before any answer is written (finish_reason="length",
            # content=None). Retry once with a bigger budget. The ceiling is
            # deliberately modest: OpenRouter rejects a request whose
            # worst-case token cost exceeds the account's remaining credit
            # with a 402, so an unbounded escalation would turn an empty
            # reply into a hard payment error.
            if not response.success and response.code == 'empty_response':
                bigger = min(max(max_tokens * 2, 1024), 2048)
                # Only worth a second call if the headroom is real: going from
                # 2000 to the 2048 ceiling would almost certainly be cut off
                # again, so move on to the next model instead.
                if bigger >= max_tokens * 1.5:
                    logger.info(
                        'Empty reply from %s at max_tokens=%s; retrying at %s',
                        candidate, max_tokens, bigger)
                    response = self._complete_once(
                        candidate, messages, temperature, bigger,
                        response_format, timeout, max_retries=0,
                    )
            elif not response.success and response.code == 'out_of_credit':
                # OpenRouter rejects a request whose worst-case cost exceeds
                # the account's remaining credit. Halve the request and try
                # again, which is often enough to fit inside what is left.
                smaller = max(256, max_tokens // 4)
                logger.info('Credit limit hit for %s at max_tokens=%s; '
                            'retrying at %s', candidate, max_tokens, smaller)
                response = self._complete_once(
                    candidate, messages, temperature, smaller,
                    response_format, timeout, max_retries=0,
                )
            if response.success:
                return response
            last = response
            if not _is_model_unavailable(response):
                # A genuine caller error (bad prompt, 401, 402) will not be
                # fixed by a different model.
                break
            if response.code == 'rate_limited' and not is_last:
                # A 429 on the free tier is usually a short window on the
                # shared provider, not a property of this model. Moving
                # straight to the next candidate just burns the remaining
                # candidates inside the same rate-limit window, so pause
                # first. Kept short: this runs inside a request/response.
                pause = min(
                    getattr(settings, 'AI_RETRY_BACKOFF_SECONDS', 0.6) * 2 * (index + 1),
                    3.0,
                )
                logger.info('Rate limited by %s; waiting %.1fs before '
                            'trying %s', candidate, pause, candidates[index + 1])
                time.sleep(pause)

        logger.warning('Text model attempt(s) failed after %d of %d candidate(s): %s',
                       attempted, len(candidates), last.code if last else 'unknown')
        return last or AIResponseFactory.failure('api_error', 'AI service error.')

    def _complete_once(self, model, messages, temperature, max_tokens,
                       response_format, timeout, max_retries):
        """One chat/completions attempt against a single model."""
        previous_timeout, previous_retries = self.timeout, self.max_retries
        if timeout is not None:
            self.timeout = timeout
        self.max_retries = max_retries
        try:
            payload = {
                'model': model,
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens,
            }
            if response_format:
                payload['response_format'] = response_format

            result = self.execute(
                endpoint=_CHAT_PATH, payload=payload, use_cache=False,
            )
        finally:
            self.timeout = previous_timeout
            self.max_retries = previous_retries

        if not result.success:
            return result

        choices = (result.data or {}).get('choices') or []
        message = (choices[0].get('message') or {}) if choices else {}
        finish_reason = (choices[0].get('finish_reason') if choices else None)

        content = _extract_content(message)
        # ``length`` means generation was cut off mid-answer, so the text is
        # incomplete even when non-empty. Reporting it as a model failure is
        # what lets the caller retry with a bigger budget, and it stops a
        # half-written JSON array from being parsed into garbage keywords.
        if not content or finish_reason == 'length':
            return AIResponseFactory.failure(
                'empty_response',
                'The AI service returned an incomplete response.')

        return AIResponseFactory.success(
            content=content, model=(result.data or {}).get('model', model),
        )

    def image_guidance(self, image_bytes: bytes, *, image_format: str = 'JPEG',
                       timeout: Optional[float] = None) -> dict:
        """Ask the vision model how this specific photo should be treated.

        Returns a dict of conservative, bounded parameters. Any failure returns
        an empty dict: the advisor is an optimisation, never a dependency, so
        a keyless or rate-limited deployment still enhances images.
        """
        system = (
            'You are an ecommerce photography technician advising on a single '
            'product photo for a marketplace listing. You never invent or '
            'describe artwork. You only report what you can see and return '
            'strict JSON.'
        )
        prompt = (
            'Look at this product photo and report: how clean and uniform the '
            'background is; whether the product is centred; how underexposed or '
            'overexposed it is; and whether it looks sharp or soft.\n'
            'Use these exact keys with these exact value sets:\n'
            '  "background": "clean" | "cluttered" | "none"\n'
            '  "centred": true | false\n'
            '  "exposure": "dark" | "ok" | "bright"\n'
            '  "sharpness": "sharp" | "soft"\n'
            '  "remove_background": true | false\n'
            '  "notes": one short sentence\n'
            'Set remove_background to false unless the background is clearly '
            'uniform and distinct from the product.'
        )
        previous = self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            response = self.describe_image(
                image_bytes, prompt=prompt, schema_hint=None
            )
        finally:
            self.timeout = previous

        if not response.success:
            logger.info('Vision advisor unavailable: %s', response.error)
            return {}

        parsed = self.extract_json(response.data.get('content') if isinstance(response.data, dict) else '')
        if not isinstance(parsed, dict):
            return {}
        return _sanitise_guidance(parsed)


_ALLOWED = {
    'background': {'clean', 'cluttered', 'none'},
    'exposure': {'dark', 'ok', 'bright'},
    'sharpness': {'sharp', 'soft'},
}


def _sanitise_guidance(raw: dict) -> dict:
    """Whitelist keys and values so a bad model reply cannot steer the pipeline."""
    out = {}
    for key, allowed in _ALLOWED.items():
        value = raw.get(key)
        if isinstance(value, str) and value.lower() in allowed:
            out[key] = value.lower()
    if isinstance(raw.get('centred'), bool):
        out['centred'] = raw['centred']
    if isinstance(raw.get('remove_background'), bool):
        out['remove_background'] = raw['remove_background']
    notes = raw.get('notes')
    if isinstance(notes, str):
        out['notes'] = notes[:200]
    return out


# Small local factory so this module does not need to import AIResponse from
# two places; kept trivial on purpose.
class AIResponseFactory:
    @staticmethod
    def success(content, model=''):
        from .base import AIResponse

        return AIResponse(success=True, data={'content': content, 'model': model})

    @staticmethod
    def failure(code, message):
        from .base import AIResponse

        return AIResponse(success=False, error=message, code=code)
