"""URLs for the AI services (image, voice, text).

Mounted under ``ai/`` in the project urls:
    /ai/image/enhance/
    /ai/image/upload/
    /ai/image/status/<uuid>/
    /ai/image/select/
    /ai/image/draft/
    /ai/voice/transcribe/
    /ai/voice/synthesise/
    /ai/text/complete/
    /ai/text/product/catalog/
    /ai/text/product/description/
    /ai/text/product/keywords/
    /ai/text/product/tags/
    /ai/text/product/rewrite/
    /ai/health/
"""

from django.urls import path

from . import views

app_name = 'ai_services'

urlpatterns = [
    # Image enhancement
    path('image/enhance/', views.enhance, name='enhance'),
    path('image/upload/', views.upload_photo, name='upload_photo'),
    path('image/status/<uuid:job_id>/', views.status, name='status'),
    path('image/select/', views.select, name='select'),
    path('image/draft/', views.draft, name='draft'),

    # Voice (STT / TTS)
    path('voice/transcribe/', views.transcribe, name='transcribe'),
    path('voice/synthesise/', views.synthesise, name='synthesise'),

    # Text (completion + ecommerce helpers)
    path('text/complete/', views.complete, name='complete'),
    path('text/product/catalog/', views.catalog, name='catalog'),
    path('text/product/description/', views.product_description, name='product_description'),
    path('text/product/keywords/', views.product_keywords, name='product_keywords'),
    path('text/product/tags/', views.product_tags, name='product_tags'),
    path('text/product/rewrite/', views.rewrite_seo, name='rewrite_seo'),

    # Product publishing
    path('publish/', views.publish, name='publish'),

    # Health / capabilities
    path('health/', views.health, name='health'),
]