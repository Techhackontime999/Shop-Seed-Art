"""Local, offline speech-to-text using faster-whisper.

Why this exists
---------------
The studio needs dictation that is *free* and always available. Both earlier
options fail one of those requirements:

* The browser's ``SpeechRecognition`` ships the seller's audio to a vendor
  cloud service, is missing in Firefox, and cannot be monitored or bounded.
* An OpenRouter transcription call costs money per request, needs a key, and
  fails outright when the account has no credit.

Whisper running locally has neither problem: no key, no network, no per-request
cost, no rate limit, and the audio never leaves the machine.

Practical constraints, learned on this deployment
--------------------------------------------------
* ``faster-whisper`` imports ``av`` (PyAV) at import time. Newer PyAV wheels
  (19.x) are rejected by this host's Windows application-control policy, which
  is why ``requirements.txt`` pins ``av==14.2.0``. The app must still boot when
  the wheel is unusable, so the import is deliberately lazy and failures are
  recorded rather than retried per request.
* The model is large (about 460MB for ``small``) and takes a couple of minutes
  to load the first time, so it is loaded once per process behind a lock and
  reused. Run ``manage.py preload_speech`` to warm it outside a request.
* Transcription is CPU-bound and blocks its worker, so a semaphore caps how
  many run at once rather than letting every request queue behind the model.
"""

import io
import logging
import threading

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)

#: Whisper language codes for the studio's two supported languages.
LANGUAGES = {'hi': 'Hindi', 'en': 'English'}

SAMPLE_RATE = 16000

#: Below this the recording is treated as silence and rejected without
#: running the model at all.
SILENCE_RMS = 0.006


class SpeechError(Exception):
    """Transcription failed. ``code`` is stable and safe for the frontend."""

    def __init__(self, code, message, detail=None, status=422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.status = status


# One model per (name, device, compute_type) per process. ``None`` as a value
# records a load that already failed, so a broken install is not retried on
# every single request.
_ENGINES = {}
_ENGINES_LOCK = threading.Lock()

#: Leaves a core free for the web server instead of saturating the box.
_SEMAPHORE = threading.Semaphore(2)


def _setting(name, default):
    return getattr(settings, name, default)


def _engine_key():
    return (
        _setting('AI_SPEECH_MODEL', 'small'),
        _setting('AI_SPEECH_DEVICE', 'cpu'),
        _setting('AI_SPEECH_COMPUTE_TYPE', 'int8'),
    )


def is_available():
    """True when the faster-whisper package can be imported.

    Cheap: it only attempts the import, it loads no model.
    """
    try:
        import faster_whisper  # noqa: F401
    except Exception as exc:
        logger.debug('Local speech engine unavailable: %s', exc)
        return False
    return True


def _load_engine():
    """Return the process-wide WhisperModel, loading it on first use."""
    key = _engine_key()
    with _ENGINES_LOCK:
        engine = _ENGINES.get(key, 'missing')
        if engine != 'missing':
            return engine

        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            # A missing or policy-blocked wheel is a deployment problem, so it
            # is recorded as failed instead of retried on every request.
            _ENGINES[key] = None
            logger.error('faster-whisper cannot be imported: %s', exc)
            return None

        logger.info('Loading local speech model %s (%s/%s)', *key)
        try:
            engine = WhisperModel(key[0], device=key[1], compute_type=key[2])
        except Exception as exc:
            _ENGINES[key] = None
            logger.exception('Local speech model %s failed to load', key[0])
            return None

        _ENGINES[key] = engine
        logger.info('Local speech model %s ready', key[0])
        return engine


def is_ready():
    """True when a model is loaded and can serve a request now.

    Lets the health endpoint separate "installed but not warmed" from "not
    installed".
    """
    return _load_engine() is not None


def preload():
    """Load the model ahead of the first request. True on success."""
    return _load_engine() is not None


def _resolve_language(requested):
    """Map the frontend's 'hi'/'en'/'auto' to what Whisper expects.

    ``None`` means auto-detect, which is right for sellers who mix Hindi and
    English inside one sentence.
    """
    requested = (requested or _setting('AI_SPEECH_LANGUAGE', 'auto') or 'auto').strip()
    if requested in ('', 'auto', 'any'):
        return None
    if requested in LANGUAGES:
        return requested
    # A browser locale such as 'hi-IN'.
    prefix = requested.split('-')[0].lower()
    return prefix if prefix in LANGUAGES else None


def _decode(audio_bytes):
    """Decode any supported container to 16kHz mono float32.

    The browser sends webm/opus, but accepting wav, ogg, m4a and mp3 too means
    a seller re-testing with a phone recording still works.
    """
    from faster_whisper.audio import decode_audio

    samples = decode_audio(io.BytesIO(audio_bytes), sampling_rate=SAMPLE_RATE)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return samples


def transcribe(audio_bytes, *, language=None, prompt=None):
    """Transcribe ``audio_bytes`` and return the recognised text.

    Returns ``{'text', 'language', 'duration', 'provider', 'model'}``.
    Raises :class:`SpeechError` with a seller-safe message on failure.
    """
    if not audio_bytes:
        raise SpeechError('missing_audio', 'No audio was recorded. Please try again.')
    max_bytes = _setting('AI_SPEECH_MAX_BYTES', 25 * 1024 * 1024)
    if len(audio_bytes) > max_bytes:
        raise SpeechError(
            'audio_too_large',
            'That recording is too long. Please keep it under a couple of minutes.')

    engine = _load_engine()
    if engine is None:
        raise SpeechError(
            'speech_unavailable',
            'Voice typing is not available on this server right now.',
            detail='faster-whisper or its model could not be loaded', status=503)

    try:
        samples = _decode(audio_bytes)
    except SpeechError:
        raise
    except Exception as exc:
        logger.info('Could not decode the uploaded audio: %s', exc)
        raise SpeechError(
            'unreadable_audio',
            'That recording could not be read. Please record again.', status=422) from exc

    if samples.size == 0:
        raise SpeechError('no_speech', 'No speech was detected in that recording.')

    duration = samples.size / float(SAMPLE_RATE)

    # A tap that starts and stops in under a second is not a recording problem,
    # it is a "you tapped too fast" problem, and running the model on it only
    # produces the useless "no speech" answer after a slow load. Say which one
    # it is so the seller knows whether to speak longer or to check the mic.
    min_seconds = float(_setting('AI_SPEECH_MIN_SECONDS', 1.0))
    if duration < min_seconds:
        raise SpeechError(
            'too_short',
            'That recording was too short to understand.',
            detail='%.2fs of audio, minimum is %.2fs' % (duration, min_seconds))

    # Reject silence before the model runs: a seller who taps the mic and says
    # nothing should get an instant answer, not ten seconds of inference.
    if float(np.sqrt(np.mean(np.square(samples)))) < SILENCE_RMS:
        raise SpeechError('no_speech', 'No speech was detected in that recording.')

    truncated = False
    max_seconds = _setting('AI_SPEECH_MAX_SECONDS', 120)
    if max_seconds and duration > max_seconds:
        samples = samples[: int(max_seconds * SAMPLE_RATE)]
        duration = max_seconds
        truncated = True
        logger.info('Trimmed a recording to the %ss limit', max_seconds)

    if not _SEMAPHORE.acquire(timeout=_setting('AI_SPEECH_QUEUE_TIMEOUT', 120)):
        raise SpeechError('speech_busy', 'Voice typing is busy. Please try again in a moment.',
                          status=503)
    try:
        segments, info = engine.transcribe(
            samples,
            language=_resolve_language(language),
            beam_size=_setting('AI_SPEECH_BEAM_SIZE', 5),
            # Voice-activity filtering is what stops a paused recording from
            # making the model invent sentences to bridge the silence, but on a
            # clip this short it can discard the one sentence that was actually
            # said and leave nothing at all. So it is only used once there is
            # enough audio for a silence gap to mean something.
            vad_filter=duration >= _setting('AI_SPEECH_VAD_MIN_SECONDS', 5.0),
            condition_on_previous_text=False,
            initial_prompt=(prompt or None),
            task='transcribe',
        )
        # The segment generator is lazy, so the real work happens here.
        collected = list(segments)
    except Exception as exc:
        logger.exception('Local transcription failed')
        raise SpeechError('transcription_failed', 'Voice typing failed. Please try again.',
                          detail=str(exc)) from exc
    finally:
        _SEMAPHORE.release()

    text = ' '.join(segment.text.strip() for segment in collected).strip()
    if not text:
        raise SpeechError('no_speech', 'No speech was detected in that recording.')

    logger.info('Transcribed %.1fs of audio (%s) with %s', duration,
                getattr(info, 'language', '?'), _engine_key()[0])
    return {
        'text': text,
        'language': getattr(info, 'language', '') or '',
        'duration': round(duration, 2),
        'provider': 'local',
        'model': _engine_key()[0],
        'truncated': truncated,
    }


def status():
    """A secret-free dict for the health endpoint."""
    return {
        'engine': 'faster-whisper' if is_available() else 'unavailable',
        'model': _setting('AI_SPEECH_MODEL', 'small'),
        'ready': is_ready(),
        'provider': _setting('AI_VOICE_PROVIDER', 'local'),
        'languages': sorted(LANGUAGES),
    }
