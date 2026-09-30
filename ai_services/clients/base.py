"""Vendor-agnostic AI API client base.

Follows the conventions the project's other service layers use (see
``logistics/services`` and ``jobs/services``): a small response dataclass, a
typed error, and one place that owns timeout + retry + caching so individual
clients never hand-roll them.
"""

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    """A failure that is safe to summarise, not to dump on a seller."""

    def __init__(self, message: str, code: str = 'ai_error', retryable: bool = False,
                 details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.details = details

    def __str__(self):  # pragma: no cover - debugging aid
        return '%s (%s)' % (self.message, self.code)


@dataclass
class AIResponse:
    success: bool
    data: Any = None
    error: str = ''
    code: str = ''
    latency_ms: int = 0
    model_used: str = ''
    from_cache: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)
    raw_content: bytes = b''


class AIAPIClient:
    """Base client: timeout, bounded retry with jittered backoff, response cache.

    Subclasses implement :meth:`_request` and :meth:`_build_payload`. The
    base class is responsible for everything that is easy to get wrong per
    call site: unbounded retries, no timeout, and logging secret-bearing
    payloads.
    """

    #: Errors worth a second attempt: transport blips, 429s and 5xxs.
    RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(self, *, timeout=None, max_retries=None, base_url=None, api_key=None):
        self.timeout = timeout if timeout is not None else getattr(settings, 'AI_TIMEOUT', 20)
        self.max_retries = (
            max_retries if max_retries is not None else getattr(settings, 'AI_MAX_RETRIES', 2)
        )
        self.base_url = (base_url or getattr(settings, 'AI_BASE_URL', '')).rstrip('/')
        self.api_key = api_key if api_key is not None else getattr(settings, 'AI_API_KEY', '')
        self.session = requests.Session()

    # -- configuration -------------------------------------------------

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    # -- public API ----------------------------------------------------

    def execute(self, *, endpoint: str, payload: dict, use_cache: bool = False,
                cache_ttl: int = 3600, expect_raw: bool = False) -> AIResponse:
        """POST ``payload`` to ``endpoint`` with retries, caching and timing.

        If ``expect_raw`` is True, the response body is returned as raw bytes
        (for audio TTS, file downloads, etc.) instead of being JSON-decoded.
        """
        if not self.is_configured:
            return AIResponse(
                success=False,
                error='AI provider is not configured.',
                code='not_configured',
            )

        cache_key = None
        if use_cache:
            cache_key = self._cache_key(endpoint, payload)
            cached = cache.get(cache_key)
            if cached is not None:
                return AIResponse(
                    success=True, data=cached, model_used='cache',
                    latency_ms=0, from_cache=True,
                )

        body, last_error = self._with_retry(endpoint, payload, expect_raw)

        if not last_error and body is not None:
            if cache_key is not None and not expect_raw:
                cache.set(cache_key, body, cache_ttl)
            if expect_raw:
                return AIResponse(success=True, raw_content=body, raw=body)
            return AIResponse(success=True, data=body, raw=body)

        return AIResponse(
            success=False,
            error=last_error.get('message', 'The AI service did not respond.'),
            code=last_error.get('code', 'ai_error'),
        )

    def chat_completion(self, messages, *, model=None, temperature=0.2,
                        max_tokens=1200, response_format=None):
        """Call the chat-completions endpoint. Implemented by subclasses."""
        raise NotImplementedError

    # -- internals -----------------------------------------------------

    def _cache_key(self, endpoint: str, payload: dict) -> str:
        # Hash rather than store: prompts can be long and may contain the
        # seller's own wording, which has no business sitting in a cache
        # backend's key space in readable form.
        try:
            blob = json.dumps(payload, sort_keys=True, default=str)
        except Exception:  # pragma: no cover - defensive
            blob = repr(payload)
        digest = hashlib.sha256(
            ('%s|%s|%s' % (self.base_url, endpoint, blob)).encode('utf-8')
        ).hexdigest()
        return 'ai_cache:%s' % digest

    def _with_retry(self, endpoint: str, payload: dict, expect_raw: bool = False):
        """Attempt the request, retrying retryable failures with backoff."""
        attempts = max(1, self.max_retries + 1)
        last_error = {'message': 'The AI service did not respond.', 'code': 'ai_error'}

        for attempt in range(1, attempts + 1):
            try:
                status, data = self._request(endpoint, payload, expect_raw)
            except requests.exceptions.Timeout:
                last_error = {'message': 'The AI service timed out.', 'code': 'timeout'}
                retryable = True
            except requests.exceptions.RequestException as exc:
                last_error = {
                    'message': 'The AI service could not be reached.',
                    'code': 'network_error',
                    'detail': str(exc),
                }
                retryable = True
            else:
                if 200 <= status < 300:
                    return data, None
                last_error = self._error_for_status(status, data)
                retryable = status in self.RETRYABLE_STATUS

            if not retryable or attempt == attempts:
                break

            # Exponential backoff with jitter: avoids a thundering herd when a
            # whole demo class hits a rate limit at the same moment.
            backoff = getattr(settings, 'AI_RETRY_BACKOFF_SECONDS', 0.6) * (2 ** (attempt - 1))
            time.sleep(backoff * (0.5 + random.random() * 0.5))

        logger.warning(
            'AI request to %s failed after %d attempt(s): %s',
            endpoint, attempts, last_error.get('code'),
        )
        return None, last_error

    def _error_for_status(self, status: int, data) -> Dict[str, Any]:
        detail = ''
        if isinstance(data, dict):
            detail = str(data.get('error') or data.get('message') or '')[:400]
        if status in (401, 403):
            return {'message': 'The AI service rejected our credentials.', 'code': 'auth_error',
                    'detail': detail}
        if status == 429:
            return {'message': 'The AI service is rate limiting us.', 'code': 'rate_limited',
                    'detail': detail}
        if status >= 500:
            return {'message': 'The AI service is unavailable.', 'code': 'server_error',
                    'detail': detail}
        if status == 402:
            # Out of credit, or the requested worst-case token cost exceeds
            # what the account can still afford. A smaller request or a
            # free-tier model will succeed, so this is retriable.
            return {'message': 'The AI service is out of credit.',
                    'code': 'out_of_credit', 'detail': detail}
        if status == 404:
            # On a gateway this means the model id has no active provider,
            # which is the normal failure mode for OpenRouter's ":free" tier
            # and is worth retrying against a different model.
            return {'message': 'That AI model is not available.', 'code': 'model_unavailable',
                    'detail': detail}
        return {'message': 'The AI service returned an error.', 'code': 'api_error',
                'detail': 'status %s %s' % (status, detail)}

    def _build_messages(self, system_prompt: str, user_prompt: str):
        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

    def _request(self, endpoint: str, payload: dict):
        """Perform one HTTP call. Returns ``(status, decoded_json)``."""
        raise NotImplementedError

    @staticmethod
    def extract_json(text: str) -> Optional[dict]:
        """Pull a JSON object out of a model response.

        Models wrap JSON in prose or fenced blocks often enough that a bare
        ``json.loads`` is not enough. This is deliberately forgiving on the
        outside and strict on the inside: the first balanced ``{...}`` block
        must parse.
        """
        if not text:
            return None
        text = text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[-1]
            if text.endswith('```'):
                text = text[:-3]
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            pass

        start = text.find('{')
        while start != -1:
            depth = 0
            for index in range(start, len(text)):
                if text[index] == '{':
                    depth += 1
                elif text[index] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:index + 1])
                        except (ValueError, TypeError):
                            break
            start = text.find('{', start + 1)
        return None
