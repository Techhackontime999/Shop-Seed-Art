from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from core.ckeditor import patch_media_renderer

        patch_media_renderer()
