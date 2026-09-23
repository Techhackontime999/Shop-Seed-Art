# ai_services/urls.py
from django.urls import path
from . import views

app_name = 'ai_services'

urlpatterns = [
    # Health check
    path('health/', views.AIHealthView.as_view(), name='health'),
    
    # Catalog (multilingual product cataloging)
    path('catalog/text/', views.AICatalogView.as_view(), {'action': 'text'}, name='catalog_text'),
    path('catalog/voice/', views.AICatalogView.as_view(), {'action': 'voice'}, name='catalog_voice'),
    path('catalog/refine/', views.AICatalogView.as_view(), {'action': 'refine'}, name='catalog_refine'),
    
    # Pricing
    path('pricing/analyze/', views.AIPricingView.as_view(), {'action': 'analyze'}, name='pricing_analyze'),
    path('pricing/feedback/', views.AIPricingView.as_view(), {'action': 'feedback'}, name='pricing_feedback'),
    
    # Image enhancement
    path('image/enhance/', views.AIImageView.as_view(), {'action': 'enhance'}, name='image_enhance'),
    path('image/batch/', views.AIImageView.as_view(), {'action': 'batch'}, name='image_batch'),
    
    # Blog generation
    path('blog/generate/', views.AIBlogView.as_view(), {'action': 'generate'}, name='blog_generate'),
    
    # Shopping assistant
    path('shopping/voice/', views.AIShoppingView.as_view(), {'action': 'voice'}, name='shopping_voice'),
    path('shopping/text/', views.AIShoppingView.as_view(), {'action': 'text'}, name='shopping_text'),
    path('shopping/compare/', views.AIShoppingView.as_view(), {'action': 'compare'}, name='shopping_compare'),
]