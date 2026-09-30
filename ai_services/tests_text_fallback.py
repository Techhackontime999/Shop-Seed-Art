"""Tests for text-model fallback and content extraction.

The free (``:free``) tier of OpenRouter is dynamic, so the client must be
able to move on to another model when one is rate limited, has no active
provider, or burns its whole token budget on reasoning.
"""

import unittest
from unittest import mock

from django.test import SimpleTestCase, override_settings

from ai_services.clients.base import AIResponse
from ai_services.clients.openrouter import (
    AIResponseFactory,
    OpenRouterClient,
    _extract_content,
    _is_model_unavailable,
)

CHAT_PATH = '/chat/completions'


def completion(content, model='some-model'):
    return {
        'model': model,
        'choices': [{'message': {'role': 'assistant', 'content': content}}],
    }


def reason_only(model='reasoner'):
    """A reasoning model that spent max_tokens thinking and returned nothing."""
    return {
        'model': model,
        'choices': [{
            'message': {
                'role': 'assistant',
                'content': None,
                'reasoning': 'Let me think about this for a while...',
            }
        }],
    }


def ok(body):
    """The success shape ``AIAPIClient.execute`` really returns.

    ``data`` is the decoded JSON body, *not* ``AIResponseFactory``'s
    ``{'content': ..., 'model': ...}`` summary — that wrapper is what the
    client builds *from* this body, so a mock returning it would double-wrap
    and make every completion look empty.
    """
    return AIResponse(success=True, data=body)


class TestExtractContent(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(_extract_content({'content': '  hello  '}), 'hello')

    def test_none_is_empty(self):
        self.assertEqual(_extract_content({'content': None}), '')

    def test_missing_key_is_empty(self):
        self.assertEqual(_extract_content({}), '')

    def test_reasoning_is_never_returned_as_the_answer(self):
        """Shipping hidden chain-of-thought to a seller would be a data leak."""
        message = {'content': None, 'reasoning': 'secret chain of thought'}
        self.assertEqual(_extract_content(message), '')

    def test_list_of_parts_is_joined(self):
        message = {'content': [{'text': 'one '}, {'text': 'two'}]}
        self.assertEqual(_extract_content(message), 'one two')

    def test_non_string_content_is_empty(self):
        self.assertEqual(_extract_content({'content': 42}), '')


class TestIsModelUnavailable(unittest.TestCase):
    def test_unavailable_codes(self):
        for code in ('rate_limited', 'server_error', 'empty_response',
                     'model_unavailable'):
            self.assertTrue(
                _is_model_unavailable(AIResponseFactory.failure(code, 'x')), code)

    def test_auth_failure_is_not_retried(self):
        """A bad key fails for every model, so trying more only adds latency."""
        self.assertFalse(
            _is_model_unavailable(AIResponseFactory.failure('auth_error', 'x')))

    def test_success_is_not_unavailable(self):
        self.assertFalse(_is_model_unavailable(AIResponseFactory.success('hi')))
        self.assertFalse(_is_model_unavailable(None))


class TestModelCandidates(SimpleTestCase):
    def _client(self):
        return OpenRouterClient(api_key='test-key')

    @override_settings(AI_TEXT_MODEL='primary/model',
                       AI_TEXT_FALLBACK_MODELS='a:free, b:free ,a:free')
    def test_orders_primary_first_and_dedupes(self):
        self.assertEqual(
            self._client()._text_model_candidates(None),
            ['primary/model', 'a:free', 'b:free'])

    @override_settings(AI_TEXT_MODEL='primary', AI_TEXT_FALLBACK_MODELS='')
    def test_works_with_no_fallbacks(self):
        self.assertEqual(self._client()._text_model_candidates(None), ['primary'])

    @override_settings(AI_TEXT_MODEL='primary', AI_TEXT_FALLBACK_MODELS='primary')
    def test_never_repeats_the_primary(self):
        self.assertEqual(self._client()._text_model_candidates(None), ['primary'])

    @override_settings(AI_TEXT_MODEL='primary', AI_TEXT_FALLBACK_MODELS='free:free')
    def test_an_explicit_model_replaces_the_configured_one(self):
        """An explicit request is a deliberate choice, so it is not also a
        fallback: silently substituting another model would hide a misconfig."""
        self.assertEqual(
            self._client()._text_model_candidates('explicit'),
            ['explicit', 'free:free'])


class TestTextCompletionFallback(SimpleTestCase):
    def _client(self):
        return OpenRouterClient(api_key='test-key')

    @override_settings(AI_TEXT_MODEL='down/model',
                       AI_TEXT_FALLBACK_MODELS='good:free',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_falls_back_to_the_next_model_on_404(self):
        client = self._client()
        calls = []

        def fake_execute(endpoint, payload, use_cache=False):
            calls.append(payload['model'])
            if payload['model'] == 'down/model':
                return AIResponseFactory.failure('model_unavailable', 'no provider')
            return ok(completion('It worked'))

        client.execute = fake_execute
        result = client.text_completion('hi')
        self.assertTrue(result.success, result.error)
        self.assertEqual(calls, ['down/model', 'good:free'])

    @override_settings(AI_TEXT_MODEL='rate/model',
                       AI_TEXT_FALLBACK_MODELS='good:free',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_falls_back_on_rate_limit(self):
        client = self._client()

        def fake_execute(endpoint, payload, use_cache=False):
            if payload['model'] == 'rate/model':
                return AIResponseFactory.failure('rate_limited', 'slow down')
            return ok(completion('Recovered'))

        client.execute = fake_execute
        with mock.patch('ai_services.clients.openrouter.time.sleep') as sleep:
            result = client.text_completion('hi')
        self.assertTrue(result.success)
        self.assertEqual(result.data['content'], 'Recovered')
        # A 429 covers every model on the account, so the next candidate is
        # only worth trying after a pause.
        sleep.assert_called_once()

    @override_settings(AI_TEXT_MODEL='rate/model',
                       AI_TEXT_FALLBACK_MODELS='good:free',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_pause_before_fallback_is_bounded(self):
        """A long fallback chain must not add up to a request timeout."""
        client = self._client()
        waits = []

        def fake_execute(endpoint, payload, use_cache=False):
            return AIResponseFactory.failure('rate_limited', 'slow down')

        client.execute = fake_execute
        with mock.patch('ai_services.clients.openrouter.time.sleep',
                        side_effect=waits.append):
            client.text_completion('hi', max_tokens=400)
        self.assertTrue(waits)
        self.assertLessEqual(sum(waits), 3.0 * 3)

    @override_settings(AI_TEXT_MODEL='no/headroom:free',
                       AI_TEXT_FALLBACK_MODELS='other:free',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_skips_the_retry_when_a_bigger_budget_would_not_help(self):
        """2000 -> 2048 is not real headroom, so go straight to the next."""
        client = self._client()
        calls = []

        def fake_execute(endpoint, payload, use_cache=False):
            calls.append(payload['model'])
            if payload['model'] == 'no/headroom:free':
                return ok({'choices': [{'message': {'content': None},
                                        'finish_reason': 'length'}]})
            return ok(completion('Real answer'))

        client.execute = fake_execute
        result = client.text_completion('hi', max_tokens=2000)
        self.assertTrue(result.success)
        self.assertEqual(calls, ['no/headroom:free', 'other:free'])

    @override_settings(AI_TEXT_MODEL='thinker:free',
                       AI_TEXT_FALLBACK_MODELS='other:free',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_falls_back_when_content_is_null(self):
        """A reasoning-only response is unusable, so try the next model."""
        client = self._client()
        calls = []

        def fake_execute(endpoint, payload, use_cache=False):
            calls.append(payload['model'])
            if payload['model'] == 'thinker:free':
                from ai_services.clients.base import AIResponse
                return AIResponse(success=True, data=reason_only())
            return ok(completion('Real answer'))

        client.execute = fake_execute
        result = client.text_completion('hi')
        self.assertTrue(result.success)
        self.assertEqual(result.data['content'], 'Real answer')
        self.assertEqual(calls, ['thinker:free', 'other:free'])

    @override_settings(AI_TEXT_MODEL='bad/model',
                       AI_TEXT_FALLBACK_MODELS='other:free',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_does_not_fall_back_on_an_auth_error(self):
        client = self._client()
        calls = []

        def fake_execute(endpoint, payload, use_cache=False):
            calls.append(payload['model'])
            return AIResponseFactory.failure('auth_error', 'bad key')

        client.execute = fake_execute
        result = client.text_completion('hi')
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'auth_error')
        self.assertEqual(calls, ['bad/model'])

    @override_settings(AI_TEXT_MODEL='a/model', AI_TEXT_FALLBACK_MODELS='b/model',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_returns_failure_when_every_model_fails(self):
        client = self._client()
        client.execute = lambda *a, **k: AIResponseFactory.failure(
            'rate_limited', 'nope')
        result = client.text_completion('hi')
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'rate_limited')

    @override_settings(AI_TEXT_MODEL='a/model', AI_TEXT_FALLBACK_MODELS='',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_rejects_an_empty_prompt_without_calling_out(self):
        client = self._client()
        client.execute = mock.Mock()
        result = client.text_completion('   ')
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'empty_prompt')
        client.execute.assert_not_called()

    @override_settings(AI_TEXT_MODEL='', AI_TEXT_FALLBACK_MODELS='')
    def test_reports_missing_configuration(self):
        result = self._client().text_completion('hi')
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'not_configured')

    @override_settings(AI_TEXT_MODEL='a/model', AI_TEXT_FALLBACK_MODELS='',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_timeout_is_restored_after_each_attempt(self):
        """A per-call timeout must not leak into the next request."""
        client = self._client()
        original = client.timeout
        seen = []

        def fake_execute(endpoint, payload, use_cache=False):
            seen.append(client.timeout)
            return AIResponseFactory.failure('rate_limited', 'x')

        client.execute = fake_execute
        client.text_completion('hi', timeout=1.0)
        self.assertEqual(seen, [1.0])
        self.assertEqual(client.timeout, original)

    @override_settings(AI_TEXT_MODEL='a/model', AI_TEXT_FALLBACK_MODELS='b:free',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_timeout_override_applies_to_every_candidate(self):
        client = self._client()
        client.timeout = 5
        seen = []

        def fake_execute(endpoint, payload, use_cache=False):
            seen.append(client.timeout)
            return AIResponseFactory.failure('rate_limited', 'x')

        client.execute = fake_execute
        client.text_completion('hi', timeout=1.0)
        self.assertEqual(seen, [1.0, 1.0])
        self.assertEqual(client.timeout, 5)

    @override_settings(AI_TEXT_MODEL='a/model', AI_TEXT_FALLBACK_MODELS='b:free',
                       AI_MAX_RETRIES=2)
    def test_only_the_final_candidate_gets_a_retry_budget(self):
        """Trying every model three times would triple outage latency."""
        client = self._client()
        client.timeout = 5
        seen = []

        def fake_execute(endpoint, payload, use_cache=False):
            seen.append((payload['model'], client.max_retries))
            return AIResponseFactory.failure('rate_limited', 'x')

        client.execute = fake_execute
        client.text_completion('hi')
        self.assertEqual([m for m, _ in seen], ['a/model', 'b:free'])
        self.assertEqual(seen[0][1], 0)
        self.assertEqual(seen[1][1], 2)


class TestExtractContentIntegration(SimpleTestCase):
    @override_settings(AI_TEXT_MODEL='a/model', AI_TEXT_FALLBACK_MODELS='',
                       AI_TIMEOUT=5, AI_MAX_RETRIES=0)
    def test_model_used_is_reported(self):
        client = OpenRouterClient(api_key='test-key')
        from ai_services.clients.base import AIResponse
        client.execute = lambda *a, **k: AIResponse(
            success=True, data=completion('answer', model='served-by-x'))
        result = client.text_completion('hi')
        self.assertEqual(result.data['model'], 'served-by-x')
