"""Tests for the local speech engine.

The real Whisper model is never loaded here: it is hundreds of megabytes and
would make the suite unusable and non-hermetic. These tests pin the behaviour
around the model, which is where the real bugs live: input validation, the
silence fast path, duration capping, language resolution, the failure cache
and the seller-facing error codes. The model call itself is stubbed.

The real engine is exercised separately by ``manage.py preload_speech`` and by
using the studio.
"""

import io
import wave
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, override_settings

from ai_services.services import speech_to_text
from ai_services.services.speech_to_text import SpeechError


def wav_bytes(samples, rate=16000):
    """Wrap float samples in a 16-bit mono WAV container."""
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype('<i2').tobytes()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buf.getvalue()


def tone(seconds=1.0, rate=16000, freq=220.0):
    t = np.linspace(0, seconds, int(seconds * rate), endpoint=False)
    return (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeInfo:
    def __init__(self, language='en', duration=1.0):
        self.language = language
        self.duration = duration


class FakeEngine:
    """Stands in for faster-whisper's WhisperModel."""

    def __init__(self, segments=None, info=None):
        self.segments = segments if segments is not None else [FakeSegment(' a cotton runner ')]
        self.info = info or FakeInfo()
        self.calls = []

    def transcribe(self, samples, **kwargs):
        self.calls.append({'samples': samples, **kwargs})
        return iter(self.segments), self.info


def install_engine(engine, key=None):
    """Put ``engine`` in the module cache and restore it after the test."""
    key = key or speech_to_text._engine_key()
    speech_to_text._ENGINES[key] = engine
    return mock.patch.dict(speech_to_text._ENGINES, speech_to_text._ENGINES, clear=True)


class SpeechTestBase(SimpleTestCase):
    """Each test gets a clean engine cache and silence warnings."""

    def setUp(self):
        patcher = mock.patch.dict(speech_to_text._ENGINES, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_engine(self, engine):
        speech_to_text._ENGINES[speech_to_text._engine_key()] = engine
        return engine


class TestResolveLanguage(SpeechTestBase):
    @override_settings(AI_SPEECH_LANGUAGE='auto')
    def test_auto_detects(self):
        self.assertIsNone(speech_to_text._resolve_language(None))
        self.assertIsNone(speech_to_text._resolve_language(''))
        self.assertIsNone(speech_to_text._resolve_language('auto'))

    @override_settings(AI_SPEECH_LANGUAGE='auto')
    def test_hindi_and_english_pass_through(self):
        self.assertEqual(speech_to_text._resolve_language('hi'), 'hi')
        self.assertEqual(speech_to_text._resolve_language('en'), 'en')

    @override_settings(AI_SPEECH_LANGUAGE='auto')
    def test_browser_locale_is_reduced_to_a_code(self):
        self.assertEqual(speech_to_text._resolve_language('hi-IN'), 'hi')
        self.assertEqual(speech_to_text._resolve_language('en-GB'), 'en')

    @override_settings(AI_SPEECH_LANGUAGE='auto')
    def test_an_unknown_language_falls_back_to_detection(self):
        """Guessing 'fr' would be worse than letting Whisper decide."""
        self.assertIsNone(speech_to_text._resolve_language('fr-FR'))

    @override_settings(AI_SPEECH_LANGUAGE='en')
    def test_the_setting_is_the_default(self):
        self.assertEqual(speech_to_text._resolve_language(None), 'en')


class TestTranscribe(SpeechTestBase):
    def setUp(self):
        super().setUp()
        self.audio = wav_bytes(tone(1.0))

    def test_returns_the_text_and_metadata(self):
        engine = self.use_engine(FakeEngine())
        result = speech_to_text.transcribe(self.audio, language='en')

        self.assertEqual(result['text'], 'a cotton runner')
        self.assertEqual(result['provider'], 'local')
        self.assertEqual(result['model'], speech_to_text._engine_key()[0])
        self.assertFalse(result['truncated'])
        self.assertEqual(result['duration'], 1.0)

    def test_joins_multiple_segments(self):
        engine = FakeEngine([FakeSegment('first'), FakeSegment('second')])
        self.use_engine(engine)
        self.assertEqual(speech_to_text.transcribe(self.audio)['text'],
                         'first second')

    def test_passes_the_resolved_language_to_the_model(self):
        engine = self.use_engine(FakeEngine())
        speech_to_text.transcribe(self.audio, language='hi-IN')
        self.assertEqual(engine.calls[0]['language'], 'hi')

    def test_uses_a_prompt_when_given(self):
        engine = self.use_engine(FakeEngine())
        speech_to_text.transcribe(self.audio, prompt='cotopune, maharashtra')
        self.assertEqual(engine.calls[0]['initial_prompt'], 'cotopune, maharashtra')

    def test_empty_audio_is_rejected_before_the_model(self):
        engine = self.use_engine(FakeEngine())
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(b'')
        self.assertEqual(ctx.exception.code, 'missing_audio')
        self.assertEqual(engine.calls, [])

    @override_settings(AI_SPEECH_MAX_BYTES=1024)
    def test_a_long_recording_is_refused(self):
        engine = self.use_engine(FakeEngine())
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(b'x' * 2048)
        self.assertEqual(ctx.exception.code, 'audio_too_large')
        self.assertEqual(engine.calls, [])

    def test_silence_is_refused_without_running_the_model(self):
        """A seller who taps the mic and says nothing gets an instant answer."""
        engine = self.use_engine(FakeEngine())
        silence = wav_bytes(np.zeros(16000, dtype=np.float32))
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(silence)
        self.assertEqual(ctx.exception.code, 'no_speech')
        self.assertEqual(engine.calls, [])

    def test_a_tap_too_short_to_understand_is_refused(self):
        """A start-stop tap gets its own answer, not "no speech".

        Telling the seller to speak louder about a clip that contains no
        sentence at all sends them off fixing the wrong thing.
        """
        engine = self.use_engine(FakeEngine())
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(wav_bytes(tone(0.4)))
        self.assertEqual(ctx.exception.code, 'too_short')
        # Refused before the model is touched, so it is instant.
        self.assertEqual(engine.calls, [])

    @override_settings(AI_SPEECH_MIN_SECONDS=0.0)
    def test_the_minimum_is_configurable(self):
        self.use_engine(FakeEngine())
        result = speech_to_text.transcribe(wav_bytes(tone(0.3)))
        self.assertEqual(result['text'], 'a cotton runner')

    def test_voice_activity_filtering_is_skipped_when_the_clip_is_short(self):
        """On a short clip, VAD can discard the one sentence that was said.

        That is how "I recorded and it came back with nothing" happens, so
        short audio goes to the model whole and only longer recordings get
        the silence-gap protection.
        """
        engine = self.use_engine(FakeEngine())
        speech_to_text.transcribe(wav_bytes(tone(2.0)))
        self.assertFalse(engine.calls[0]['vad_filter'])

    def test_voice_activity_filtering_still_protects_long_recordings(self):
        engine = self.use_engine(FakeEngine())
        speech_to_text.transcribe(wav_bytes(tone(9.0)))
        self.assertTrue(engine.calls[0]['vad_filter'])

    def test_a_model_that_hears_nothing_is_refused(self):
        self.use_engine(FakeEngine(segments=[]))
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(self.audio)
        self.assertEqual(ctx.exception.code, 'no_speech')

    def test_whitespace_only_text_counts_as_no_speech(self):
        self.use_engine(FakeEngine(segments=[FakeSegment('   ')]))
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(self.audio)
        self.assertEqual(ctx.exception.code, 'no_speech')

    @override_settings(AI_SPEECH_MAX_SECONDS=2)
    def test_a_long_recording_is_capped(self):
        engine = self.use_engine(FakeEngine())
        result = speech_to_text.transcribe(wav_bytes(tone(6.0)))

        self.assertTrue(result['truncated'])
        self.assertEqual(result['duration'], 2.0)
        # The model must only ever see the capped audio.
        self.assertEqual(len(engine.calls[0]['samples']), 2 * 16000)

    @override_settings(AI_SPEECH_MAX_SECONDS=120)
    def test_a_short_recording_is_untouched(self):
        engine = self.use_engine(FakeEngine())
        result = speech_to_text.transcribe(self.audio)
        self.assertFalse(result['truncated'])
        self.assertEqual(len(engine.calls[0]['samples']), 16000)

    def test_undecodable_bytes_give_a_clean_error(self):
        self.use_engine(FakeEngine())
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(b'this is not audio at all')
        self.assertEqual(ctx.exception.code, 'unreadable_audio')

    def test_a_model_crash_is_reported_without_leaking_internals(self):
        class Broken:
            def transcribe(self, samples, **kwargs):
                raise RuntimeError('ctranslate2 exploded: /secret/path')

        self.use_engine(Broken())
        with self.assertRaises(SpeechError) as ctx:
            speech_to_text.transcribe(self.audio)
        self.assertEqual(ctx.exception.code, 'transcription_failed')
        self.assertNotIn('ctranslate2', ctx.exception.message)
        # The operator still gets the real reason in the log payload.
        self.assertIn('ctranslate2', ctx.exception.detail)

    def test_the_semaphore_is_released_after_a_failure(self):
        """A crashed model must not leak a permit and wedge the queue."""
        class Broken:
            def transcribe(self, samples, **kwargs):
                raise RuntimeError('boom')

        self.use_engine(Broken())
        for _ in range(6):
            with self.assertRaises(SpeechError):
                speech_to_text.transcribe(self.audio)
        # Both permits are free again, so this must not block.
        self.use_engine(FakeEngine())
        self.assertEqual(speech_to_text.transcribe(self.audio)['text'],
                         'a cotton runner')


class TestEngineLoading(SpeechTestBase):
    def test_a_missing_package_is_recorded_not_retried(self):
        """A broken install must not re-import on every single request."""
        broken = mock.Mock(side_effect=ImportError('No module named av'))
        with mock.patch.dict('sys.modules', {'faster_whisper': None}):
            with mock.patch('builtins.__import__', broken):
                self.assertIsNone(speech_to_text._load_engine())
        self.assertIsNone(speech_to_text._ENGINES[speech_to_text._engine_key()])

    def test_a_failed_load_is_not_retried(self):
        sentinel = None
        speech_to_text._ENGINES[speech_to_text._engine_key()] = sentinel
        with mock.patch('faster_whisper.WhisperModel', side_effect=RuntimeError('nope')):
            # Second call must reuse the recorded failure, not try again.
            self.assertIsNone(speech_to_text._load_engine())
            self.assertIsNone(speech_to_text._load_engine())

    def test_status_reports_the_configured_model(self):
        with mock.patch.object(speech_to_text, 'is_available', return_value=True):
            with mock.patch.object(speech_to_text, 'is_ready', return_value=False):
                report = speech_to_text.status()
        self.assertEqual(report['engine'], 'faster-whisper')
        self.assertFalse(report['ready'])
        self.assertEqual(sorted(report['languages']), ['en', 'hi'])

    def test_status_reports_a_missing_engine(self):
        with mock.patch.object(speech_to_text, 'is_available', return_value=False):
            self.assertEqual(speech_to_text.status()['engine'], 'unavailable')


class TestPreloadCommand(SimpleTestCase):
    def test_it_reports_success(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        with mock.patch.object(speech_to_text, 'preload', return_value=True):
            with mock.patch.object(speech_to_text, 'is_available', return_value=True):
                call_command('preload_speech', stdout=out)
        self.assertIn('ready', out.getvalue().lower())

    def test_it_reports_a_missing_package(self):
        from django.core.management import call_command
        from io import StringIO
        err = StringIO()
        with mock.patch.object(speech_to_text, 'is_available', return_value=False):
            call_command('preload_speech', stderr=err)
        self.assertIn('faster-whisper', err.getvalue())
