from django.apps import AppConfig


class AIServicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_services'
    verbose_name = 'AI Services'

    def ready(self):
        # Importing the module is enough: each check in it is registered by
        # its own @register decorator. Registering them a second time here
        # would run every check twice on `manage.py check` and make a real
        # failure look like a duplicate.
        from . import checks  # noqa: F401
