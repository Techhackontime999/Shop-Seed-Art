# ai_services/apps.py
from django.apps import AppConfig


class AIServicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_services'
    verbose_name = 'AI Services'

    def ready(self):
        # Import signals if any
        pass