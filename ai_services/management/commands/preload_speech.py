"""Warm the local speech model outside a request.

Loading ``small`` takes a couple of minutes the first time (and downloads it if
it is not cached yet). Doing that while a seller is waiting for a transcript
means a visible stall, so this is meant to run at deploy or worker start-up::

    python manage.py preload_speech

It is safe to run repeatedly: an already-loaded model is left alone.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from ai_services.services import speech_to_text


class Command(BaseCommand):
    help = 'Load the local Whisper model so the first dictation is not slow.'

    def handle(self, *args, **options):
        name = getattr(settings, 'AI_SPEECH_MODEL', 'small')
        device = getattr(settings, 'AI_SPEECH_DEVICE', 'cpu')
        compute = getattr(settings, 'AI_SPEECH_COMPUTE_TYPE', 'int8')

        if not speech_to_text.is_available():
            self.stderr.write(
                self.style.ERROR(
                    'faster-whisper is not importable. Install requirements.txt '
                    'and check that the "av" wheel is allowed on this host.'))
            return

        self.stdout.write('Loading %s (%s/%s), first run may download ~460MB...'
                          % (name, device, compute))
        started = time.time()
        if not speech_to_text.preload():
            self.stderr.write(self.style.ERROR('The speech model failed to load.'))
            return
        self.stdout.write(self.style.SUCCESS(
            'Speech model %s ready in %.1fs.' % (name, time.time() - started)))
