"""Voice + Text endpoint tests."""

from unittest import mock
import unittest

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
import json

from .models import EnhancementStatus, ImageEnhancementJob, Selection
from .clients.base import AIResponse
from .services.image_enhancer import EnhancementError
from .services.speech_to_text import SpeechError
from .services.voice_text import (
    PRODUCT_CATALOG_SYSTEM,
    VoiceTextError,
    generate_product_catalog,
    generate_product_description,
    generate_seo_keywords,
    strip_markdown,
    text_completion,
)
from .utils.image_validation import ImageValidationError


class VoiceTextTestBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('seller', 's@example.com', 'pw')
        self.client = Client()
        self.client.force_login(self.user)


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none',
                   AI_VOICE_PROVIDER='local')
class TestTranscribeEndpoint(VoiceTextTestBase):
    def setUp(self):
        super().setUp()
        self.url = '/ai/voice/transcribe/'

    def test_requires_login(self):
        self.assertEqual(Client().post(self.url, {'audio': b'test'}).status_code, 302)

    def test_requires_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        audio = SimpleUploadedFile('test.webm', b'fake audio', content_type='audio/webm')
        response = csrf_client.post(self.url, {'audio': audio})
        self.assertEqual(response.status_code, 403)

    def test_rejects_missing_audio(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.json()['error']['code'], 'missing_audio')

    @mock.patch('ai_services.views.transcribe_speech')
    def test_successful_transcription(self, mock_transcribe):
        mock_transcribe.return_value = {
            'text': 'Handwoven cotton runner', 'language': 'en', 'duration': 4.2,
            'provider': 'local', 'model': 'small', 'truncated': False,
        }
        audio = SimpleUploadedFile('test.webm', b'fake audio', content_type='audio/webm')
        response = self.client.post(self.url, {'audio': audio, 'language': 'en'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['text'], 'Handwoven cotton runner')
        self.assertEqual(body['model'], 'small')
        # The frontend needs to know the engine so it can explain the source.
        self.assertEqual(body['provider'], 'local')
        self.assertEqual(body['language'], 'en')
        # The chosen language is passed through to the engine.
        self.assertEqual(mock_transcribe.call_args.kwargs['language'], 'en')

    @mock.patch('ai_services.views.transcribe_speech')
    def test_speech_unavailable_asks_the_browser_to_take_over(self, mock_transcribe):
        """A 503 with this code is the signal for the browser fallback."""
        mock_transcribe.side_effect = SpeechError(
            'speech_unavailable', 'Voice typing is not available on this server right now.',
            status=503)
        audio = SimpleUploadedFile('test.webm', b'fake audio', content_type='audio/webm')
        response = self.client.post(self.url, {'audio': audio})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'speech_unavailable')

    @mock.patch('ai_services.views.transcribe_speech')
    def test_no_speech_is_a_422_with_seller_copy(self, mock_transcribe):
        mock_transcribe.side_effect = SpeechError(
            'no_speech', 'No speech was detected in that recording.')
        audio = SimpleUploadedFile('test.webm', b'fake audio', content_type='audio/webm')
        response = self.client.post(self.url, {'audio': audio})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'no_speech')

    @override_settings(AI_VOICE_PROVIDER='openrouter')
    @mock.patch('ai_services.views.transcribe_audio')
    def test_openrouter_is_opt_in_only(self, mock_transcribe):
        mock_transcribe.return_value = {'text': 'From the gateway', 'model': 'whisper-1'}
        audio = SimpleUploadedFile('test.webm', b'fake audio', content_type='audio/webm')
        response = self.client.post(self.url, {'audio': audio})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'openrouter')

    @override_settings(AI_VOICE_PROVIDER='openrouter')
    @mock.patch('ai_services.views.transcribe_audio')
    def test_openrouter_failures_are_reported(self, mock_transcribe):
        mock_transcribe.side_effect = VoiceTextError('transcription_failed', 'Failed')
        audio = SimpleUploadedFile('test.webm', b'fake audio', content_type='audio/webm')
        response = self.client.post(self.url, {'audio': audio})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'transcription_failed')

    @override_settings(AI_VOICE_PROVIDER='browser')
    def test_browser_provider_never_calls_an_engine(self):
        """With the client transcribing, the server must stay out of the way."""
        audio = SimpleUploadedFile('test.webm', b'fake audio', content_type='audio/webm')
        with mock.patch('ai_services.views.transcribe_speech') as mock_local:
            response = self.client.post(self.url, {'audio': audio})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'speech_unavailable')
        mock_local.assert_not_called()


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestSynthesiseEndpoint(VoiceTextTestBase):
    def setUp(self):
        super().setUp()
        self.url = '/ai/voice/synthesise/'

    def test_requires_login(self):
        self.assertEqual(Client().post(self.url, json.dumps({'text': 'hi'}), content_type='application/json').status_code, 302)

    def test_rejects_empty_text(self):
        response = self.client.post(self.url, json.dumps({'text': ''}), content_type='application/json')
        self.assertEqual(response.json()['error']['code'], 'empty_text')

    @mock.patch('ai_services.views.text_to_speech')
    def test_successful_synthesis(self, mock_tts):
        mock_tts.return_value = {'audio': b'ID3fake-mp3-bytes', 'model': 'tts-1'}
        response = self.client.post(
            self.url, json.dumps({'text': 'Hello', 'format': 'mp3'}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'audio/mp3')
        self.assertEqual(response['X-AI-Model'], 'tts-1')
        self.assertIn('speech.mp3', response['Content-Disposition'])
        self.assertEqual(b''.join(response.streaming_content), b'ID3fake-mp3-bytes')

    @mock.patch('ai_services.views.text_to_speech')
    def test_handles_voice_text_error(self, mock_tts):
        mock_tts.side_effect = VoiceTextError('tts_failed', 'Failed')
        response = self.client.post(self.url, json.dumps({'text': 'Hello'}), content_type='application/json')
        self.assertEqual(response.status_code, 422)


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestTextCompleteEndpoint(VoiceTextTestBase):
    def setUp(self):
        super().setUp()
        self.url = '/ai/text/complete/'

    def test_requires_login(self):
        self.assertEqual(Client().post(self.url, json.dumps({'prompt': 'hi'}), content_type='application/json').status_code, 302)

    def test_rejects_empty_prompt(self):
        response = self.client.post(self.url, json.dumps({'prompt': ''}), content_type='application/json')
        self.assertEqual(response.json()['error']['code'], 'empty_prompt')

    @mock.patch('ai_services.views.text_completion')
    def test_successful_completion(self, mock_complete):
        mock_complete.return_value = {'text': 'Completion result', 'model': 'llama'}
        response = self.client.post(self.url, json.dumps({'prompt': 'Test'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['text'], 'Completion result')

    @mock.patch('ai_services.views.text_completion')
    def test_passes_optional_params(self, mock_complete):
        mock_complete.return_value = {'text': 'OK', 'model': 'llama'}
        self.client.post(self.url, json.dumps({
            'prompt': 'Test',
            'system_prompt': 'Sys',
            'temperature': 0.5,
            'max_tokens': 500,
            'response_format': {'type': 'json_object'},
        }), content_type='application/json')
        call = mock_complete.call_args
        self.assertEqual(call.kwargs['system_prompt'], 'Sys')
        self.assertEqual(call.kwargs['temperature'], 0.5)
        self.assertEqual(call.kwargs['max_tokens'], 500)
        self.assertEqual(call.kwargs['response_format'], {'type': 'json_object'})


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestProductCatalogEndpoint(VoiceTextTestBase):
    """One call has to fill the title, the body and the search terms."""

    def setUp(self):
        super().setUp()
        self.url = '/ai/text/product/catalog/'

    def test_requires_login(self):
        self.assertEqual(
            Client().post(self.url, json.dumps({'title': 'Pot'}),
                          content_type='application/json').status_code, 302)

    def test_rejects_an_empty_request(self):
        response = self.client.post(self.url, json.dumps({}), content_type='application/json')
        self.assertEqual(response.json()['error']['code'], 'missing_title')

    def test_seller_notes_alone_are_enough(self):
        with mock.patch('ai_services.views.generate_product_catalog') as mock_gen:
            mock_gen.return_value = {
                'title': 'Handwoven Runner', 'description': 'A cotton runner.',
                'keywords': ['handwoven', 'cotton'], 'model': 'llama',
            }
            response = self.client.post(
                self.url, json.dumps({'seller_notes': 'I wove this runner by hand'}),
                content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], 'Handwoven Runner')
        self.assertEqual(response.json()['keywords'], ['handwoven', 'cotton'])
        # The seller's own words must reach the model, not just the title.
        self.assertEqual(mock_gen.call_args[0][0]['seller_notes'],
                         'I wove this runner by hand')

    @mock.patch('ai_services.views.generate_product_catalog')
    def test_returns_the_keys_the_studio_reads(self, mock_gen):
        mock_gen.return_value = {
            'title': 'T', 'description': 'D', 'keywords': ['a'], 'model': 'm',
            'category': 'Books', 'subcategory': '',
        }
        response = self.client.post(
            self.url, json.dumps({'title': 'Pot'}), content_type='application/json')
        body = response.json()
        self.assertEqual(
            set(body),
            {'success', 'title', 'description', 'keywords', 'model',
             'category', 'subcategory'})
        # The pickers are filled from the answer, so the placement has to be
        # on the wire even when the studio asked for no placement at all.
        self.assertEqual(body['category'], 'Books')
        self.assertEqual(body['subcategory'], '')

    @mock.patch('ai_services.views.generate_product_catalog')
    def test_a_placement_the_service_did_not_return_is_never_invented(self,
                                                                      mock_gen):
        """The view must pass through what the taxonomy resolved, not guess a
        department of its own."""
        mock_gen.return_value = {
            'title': 'T', 'description': 'D', 'keywords': ['a'], 'model': 'm',
        }
        response = self.client.post(
            self.url, json.dumps({'title': 'Pot'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['category'], '')
        self.assertEqual(body['subcategory'], '')

    @mock.patch('ai_services.views.generate_product_catalog')
    def test_passes_the_listing_language_through(self, mock_gen):
        mock_gen.return_value = {
            'title': 'T', 'description': 'D', 'keywords': [], 'model': 'm',
        }
        self.client.post(self.url, json.dumps({'title': 'Pot', 'language': 'hi'}),
                         content_type='application/json')
        self.assertEqual(mock_gen.call_args[0][0]['language'], 'hi')

    @mock.patch('ai_services.views.generate_product_catalog')
    def test_handles_voice_text_error(self, mock_gen):
        mock_gen.side_effect = VoiceTextError('openrouter_failed', 'Failed')
        response = self.client.post(
            self.url, json.dumps({'title': 'Pot'}), content_type='application/json')
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.json()['success'])

    def test_is_rate_limited(self):
        from django.core.cache import cache
        cache.clear()
        with mock.patch('ai_services.views.generate_product_catalog') as mock_gen, \
                override_settings(AI_TEXT_RATE_LIMIT=1):
            mock_gen.return_value = {
                'title': 'T', 'description': 'D', 'keywords': [], 'model': 'm',
            }
            self.assertEqual(
                self.client.post(self.url, json.dumps({'title': 'Pot'}),
                                 content_type='application/json').status_code, 200)
            limited = self.client.post(self.url, json.dumps({'title': 'Pot'}),
                                       content_type='application/json')
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()['error']['code'], 'rate_limited')
        cache.clear()


class TestGenerateProductCatalogService(TestCase):
    """The single call that fills the title, the body and the keywords.

    A real model fences its JSON, answers in prose, gets cut off mid-document
    or answers in the wrong language. Every one of those has to produce
    something the studio can show, because an empty field is indistinguishable
    from a failure the seller cannot fix.

    This is a ``TestCase`` rather than a ``SimpleTestCase`` because the call
    reads the shop's own taxonomy to decide where the listing belongs: it is
    no longer a pure function of the prompt. An empty taxonomy here is itself
    worth testing -- the studio has to survive a shop that has not been
    categorised yet.
    """

    def _run(self, reply, product_data=None):
        with mock.patch('ai_services.services.voice_text.text_completion') as mock_text:
            mock_text.return_value = {'text': reply, 'model': 'llama'}
            result = generate_product_catalog(product_data or {'seller_notes': 'A pot'})
        return result, mock_text.call_args

    def test_reads_a_well_formed_reply(self):
        result, _ = self._run(json.dumps({
            'title': 'Handwoven Cotton Runner',
            'description': 'A soft runner woven on a pit loom.',
            'keywords': ['handwoven', 'cotton runner'],
        }))
        self.assertEqual(result['title'], 'Handwoven Cotton Runner')
        self.assertEqual(result['description'], 'A soft runner woven on a pit loom.')
        self.assertEqual(result['keywords'], ['handwoven', 'cotton runner'])

    def test_reads_a_fenced_reply(self):
        reply = '```json\n{"title": "Clay Pot", "description": "A clay pot."}\n```'
        result, _ = self._run(reply)
        self.assertEqual(result['title'], 'Clay Pot')
        self.assertEqual(result['description'], 'A clay pot.')

    def test_a_prose_reply_still_yields_a_title(self):
        reply = 'Handwoven Cotton Runner. A soft runner woven on a pit loom.'
        result, _ = self._run(reply)
        self.assertEqual(result['title'], 'Handwoven Cotton Runner')
        self.assertIn('pit loom', result['description'])

    def test_a_truncated_reply_is_repaired(self):
        result, _ = self._run('{"title": "Clay Pot", "description": "A clay pot made')
        self.assertEqual(result['title'], 'Clay Pot')

    def test_a_title_is_lifted_from_prose_when_json_has_none(self):
        result, _ = self._run(json.dumps({'description': 'A clay pot made by hand. It is blue.'}))
        # No trailing full stop: this string goes on the storefront as-is.
        self.assertEqual(result['title'], 'A clay pot made by hand')
        self.assertIn('It is blue', result['description'])

    def test_markdown_is_stripped_from_the_copy(self):
        result, _ = self._run(json.dumps({
            'title': '**Clay Pot**',
            'description': '- Handmade\n- Glazed',
        }))
        self.assertEqual(result['title'], 'Clay Pot')
        self.assertNotIn('**', result['description'])
        self.assertNotIn('-', result['description'].split('Handmade')[0])

    def test_an_unusable_reply_returns_empty_fields_rather_than_raising(self):
        result, _ = self._run('   ')
        self.assertEqual(result['title'], '')
        self.assertEqual(result['description'], '')
        self.assertEqual(result['keywords'], [])

    def test_keywords_are_capped_and_deduplicated(self):
        reply = json.dumps({
            'title': 'T', 'description': 'D',
            'keywords': ['a'] + ['kw%d' % i for i in range(30)] + ['a'],
        })
        result, _ = self._run(reply)
        self.assertEqual(result['keywords'][0], 'a')
        self.assertEqual(len(result['keywords']), 10)
        self.assertEqual(len(set(result['keywords'])), len(result['keywords']))

    def test_hindi_is_an_instruction_not_a_fact(self):
        _, call = self._run('t', {'seller_notes': 'A pot', 'language': 'hi'})
        self.assertIn('Hindi', call.kwargs['system_prompt'])

    def test_an_unsupported_language_asks_for_nothing(self):
        """An unrecognised language must not produce a garbled instruction."""
        _, call = self._run('t', {'seller_notes': 'A pot', 'language': 'fr'})
        self.assertEqual(call.kwargs['system_prompt'], PRODUCT_CATALOG_SYSTEM)

    def test_a_supported_language_appends_to_the_base_prompt(self):
        _, call = self._run('t', {'seller_notes': 'A pot', 'language': 'en'})
        self.assertTrue(call.kwargs['system_prompt'].startswith(PRODUCT_CATALOG_SYSTEM))
        self.assertGreater(len(call.kwargs['system_prompt']), len(PRODUCT_CATALOG_SYSTEM))

    def test_seller_notes_reach_the_model_as_facts(self):
        _, call = self._run('t', {'seller_notes': 'My grandmother glazed it'})
        self.assertIn('My grandmother glazed it', call.args[0])


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestProductDescriptionEndpoint(VoiceTextTestBase):
    def setUp(self):
        super().setUp()
        self.url = '/ai/text/product/description/'

    def test_requires_title(self):
        response = self.client.post(self.url, json.dumps({}), content_type='application/json')
        self.assertEqual(response.json()['error']['code'], 'missing_title')

    @mock.patch('ai_services.views.generate_product_description')
    def test_successful_generation(self, mock_gen):
        mock_gen.return_value = {'text': 'Beautiful handmade pot.', 'model': 'llama'}
        response = self.client.post(self.url, json.dumps({'title': 'Pot'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['description'], 'Beautiful handmade pot.')


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestProductKeywordsEndpoint(VoiceTextTestBase):
    def setUp(self):
        super().setUp()
        self.url = '/ai/text/product/keywords/'

    @mock.patch('ai_services.views.generate_seo_keywords')
    def test_successful_keywords(self, mock_kw):
        mock_kw.return_value = ['pottery', 'handmade', 'ceramic']
        response = self.client.post(self.url, json.dumps({'title': 'Pot'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['keywords'], ['pottery', 'handmade', 'ceramic'])


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestProductTagsEndpoint(VoiceTextTestBase):
    def setUp(self):
        super().setUp()
        self.url = '/ai/text/product/tags/'

    @mock.patch('ai_services.views.generate_product_tags')
    def test_successful_tags(self, mock_tags):
        mock_tags.return_value = ['home', 'decor', 'kitchen']
        response = self.client.post(self.url, json.dumps({'title': 'Pot'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['tags'], ['home', 'decor', 'kitchen'])


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestRewriteSEOEndpoint(VoiceTextTestBase):
    def setUp(self):
        super().setUp()
        self.url = '/ai/text/product/rewrite/'

    def test_requires_text(self):
        response = self.client.post(self.url, json.dumps({}), content_type='application/json')
        self.assertEqual(response.json()['error']['code'], 'empty_text')

    @mock.patch('ai_services.views.rewrite_for_seo')
    def test_successful_rewrite(self, mock_rewrite):
        mock_rewrite.return_value = {'text': 'Rewritten description.', 'model': 'llama'}
        response = self.client.post(self.url, json.dumps({'text': 'Original'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['text'], 'Rewritten description.')


@override_settings(AI_API_KEY='test-key', IMAGE_ENHANCEMENT_ADVISOR='none')
class TestHealthEndpoint(VoiceTextTestBase):
    def test_reports_capabilities(self):
        response = self.client.get('/ai/health/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn('provider', body)
        self.assertIn('is_ai', body)
        self.assertIn('backgrounds', body)
        # Voice/text specific fields
        self.assertIn('advisor_enabled', body)
        self.assertIn('neural_segmentation', body)
        self.assertIn('classical_segmentation', body)


class TestSellerFacingMessages(SimpleTestCase):
    """The seller sees our copy, never the provider's internal wording."""

    @mock.patch('ai_services.services.voice_text._client')
    def test_rate_limit_is_translated(self, factory):
        failure = AIResponse(success=False, code='rate_limited',
                             error='The AI service is rate limiting us.')
        factory.return_value.text_completion.return_value = failure

        with self.assertRaises(VoiceTextError) as ctx:
            generate_seo_keywords({'title': 'Runner'})

        self.assertEqual(ctx.exception.code, 'rate_limited')
        self.assertNotIn('AI service', ctx.exception.message)
        self.assertIn('busy', ctx.exception.message)
        # The provider's own wording is kept for the logs, not the browser.
        self.assertIn('rate limiting us', ctx.exception.detail)

    @mock.patch('ai_services.services.voice_text._client')
    def test_out_of_credit_is_translated(self, factory):
        failure = AIResponse(success=False, code='out_of_credit',
                             error='The AI service is out of credit.')
        factory.return_value.text_completion.return_value = failure

        with self.assertRaises(VoiceTextError) as ctx:
            generate_seo_keywords({'title': 'Runner'})
        self.assertNotIn('credit', ctx.exception.message.lower())

    @mock.patch('ai_services.services.voice_text._client')
    def test_an_unmapped_code_still_reads_safely(self, factory):
        failure = AIResponse(success=False, code='something_new',
                             error='Internal detail leaked here.')
        factory.return_value.text_completion.return_value = failure

        with self.assertRaises(VoiceTextError) as ctx:
            generate_seo_keywords({'title': 'Runner'})
        self.assertEqual(ctx.exception.code, 'something_new')
        self.assertNotIn('leaked', ctx.exception.message)
        # The code still reaches the frontend so the UI can react to it.
        self.assertIn('leaked', ctx.exception.detail)

    @mock.patch('ai_services.services.voice_text._client')
    def test_empty_prompt_does_not_leak_internals(self, factory):
        factory.return_value.text_completion.return_value = AIResponse(
            success=True, data={'content': ''})
        with self.assertRaises(VoiceTextError) as ctx:
            text_completion('   ')
        self.assertEqual(ctx.exception.code, 'empty_prompt')
        self.assertIn('description', ctx.exception.message.lower())
        factory.return_value.text_completion.assert_not_called()


class TestStripMarkdown(SimpleTestCase):
    """Descriptions are shown as plain text, so markup must not survive."""

    def test_removes_bold(self):
        self.assertEqual(
            strip_markdown('**Handwoven Cotton Table Runner**\n\nMade of cotton.'),
            'Handwoven Cotton Table Runner\n\nMade of cotton.')

    def test_removes_bullets_and_headings(self):
        self.assertEqual(
            strip_markdown('## Features\n- Soft\n- Breathable'),
            'Features\nSoft\nBreathable')

    def test_removes_code_fences(self):
        self.assertEqual(strip_markdown('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_removes_single_emphasis(self):
        self.assertEqual(strip_markdown('a *soft* runner'), 'a soft runner')

    def test_keeps_an_unpaired_asterisk(self):
        """'star*' is prose, not emphasis, and must survive."""
        self.assertEqual(strip_markdown('a star* here'), 'a star* here')

    def test_keeps_intraword_underscores(self):
        self.assertEqual(strip_markdown('hand_woven_item'),
                         'hand_woven_item')

    def test_collapses_runs_of_blank_lines(self):
        self.assertEqual(strip_markdown('One.\n\n\n\nTwo.'), 'One.\n\nTwo.')

    def test_leaves_plain_prose_untouched(self):
        self.assertEqual(strip_markdown('A 50% off sale, ~5 cm fringing.'),
                         'A 50% off sale, ~5 cm fringing.')

    def test_handles_empty(self):
        self.assertEqual(strip_markdown(''), '')
        self.assertEqual(strip_markdown(None), '')


class TestDescriptionIsStripped(SimpleTestCase):
    """The service, not the view, is responsible for clean seller copy."""

    def test_markdown_is_removed_from_the_generated_description(self):
        completed = mock.Mock(return_value={
            'text': '**Runner**\n- cotton\n- soft',
            'model': 'some:free',
        })
        with mock.patch('ai_services.services.voice_text.text_completion', completed):
            result = generate_product_description({'title': 'Runner'})

        self.assertNotIn('**', result['text'])
        self.assertNotIn('- ', result['text'])
        self.assertIn('Runner', result['text'])
        # The model that actually answered is still reported.
        self.assertEqual(result['model'], 'some:free')