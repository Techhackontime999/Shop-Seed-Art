# ai_services/views.py
import json
import logging
from typing import Dict, Any

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings

from .services import AIOrchestrator, CatalogService, PricingService, ImageService, BlogService
from .clients import OpenRouterFallbackClient

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class AICatalogView(View):
    """API endpoints for multilingual cataloging"""
    
    def post(self, request, action=None):
        try:
            if action == 'text':
                return self.catalog_text(request)
            elif action == 'voice':
                return self.catalog_voice(request)
            elif action == 'refine':
                return self.catalog_refine(request)
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
        except Exception as e:
            logger.exception("Catalog API error")
            return JsonResponse({'error': str(e)}, status=500)
    
    def catalog_text(self, request):
        """Process text input -> structured catalog data"""
        data = json.loads(request.body) if request.body else {}
        text = data.get('text', '')
        language = data.get('language', 'en-IN')
        category_hint = data.get('category_hint')
        
        if not text:
            return JsonResponse({'error': 'Text is required'}, status=400)
        
        client = OpenRouterFallbackClient()
        catalog = CatalogService(client)
        
        # Run async in sync context
        import asyncio
        result = asyncio.run(catalog.process_text(text, language, category_hint))
        
        return JsonResponse(result)
    
    def catalog_voice(self, request):
        """Process voice transcription -> structured catalog data"""
        audio_text = request.POST.get('audio_text', '')
        language = request.POST.get('language', 'hi-IN')
        category_hint = request.POST.get('category_hint')
        
        if not audio_text:
            return JsonResponse({'error': 'Audio text is required'}, status=400)
        
        client = OpenRouterFallbackClient()
        catalog = CatalogService(client)
        
        import asyncio
        result = asyncio.run(catalog.process_voice(audio_text, language, category_hint))
        
        return JsonResponse(result)
    
    def catalog_refine(self, request):
        """Refine catalog data with seller corrections"""
        data = json.loads(request.body) if request.body else {}
        original = data.get('original', {})
        corrections = data.get('corrections', {})
        
        client = OpenRouterFallbackClient()
        catalog = CatalogService(client)
        
        import asyncio
        result = asyncio.run(catalog.refine(original, corrections))
        
        return JsonResponse(result)


@method_decorator(csrf_exempt, name='dispatch')
class AIPricingView(View):
    """API endpoints for dynamic pricing"""
    
    def post(self, request, action=None):
        try:
            if action == 'analyze':
                return self.analyze(request)
            elif action == 'feedback':
                return self.feedback(request)
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
        except Exception as e:
            logger.exception("Pricing API error")
            return JsonResponse({'error': str(e)}, status=500)
    
    def analyze(self, request):
        """Analyze product and suggest pricing"""
        data = json.loads(request.body) if request.body else {}
        product = data.get('product', {})
        
        client = OpenRouterFallbackClient()
        pricing = PricingService(client)
        
        import asyncio
        result = asyncio.run(pricing.analyze(product))
        
        return JsonResponse(result)
    
    def feedback(self, request):
        """Record seller feedback on pricing"""
        data = json.loads(request.body) if request.body else {}
        product_id = data.get('product_id')
        suggested = data.get('suggested_price')
        action = data.get('action')  # accepted, rejected, modified
        final = data.get('final_price')
        notes = data.get('notes', '')
        
        client = OpenRouterFallbackClient()
        pricing = PricingService(client)
        
        import asyncio
        result = asyncio.run(pricing.process_feedback(product_id, suggested, action, final, notes))
        
        return JsonResponse(result)


@method_decorator(csrf_exempt, name='dispatch')
class AIImageView(View):
    """API endpoints for image enhancement"""
    
    def post(self, request, action=None):
        try:
            if action == 'enhance':
                return self.enhance(request)
            elif action == 'batch':
                return self.batch_enhance(request)
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
        except Exception as e:
            logger.exception("Image API error")
            return JsonResponse({'error': str(e)}, status=500)
    
    def enhance(self, request):
        """Enhance single image"""
        # In production: receive file, process, return enhanced URL
        # For demo: return mock response
        return JsonResponse({
            'job_id': 'mock-job-id',
            'status': 'completed',
            'enhanced_url': 'https://via.placeholder.com/1000x1000/FFFFFF/000000?text=AI+Enhanced',
            'metadata': {
                'preset_used': request.POST.get('preset', 'auto'),
                'processing_time_ms': 1200,
                'quality_score': 0.94
            }
        })
    
    def batch_enhance(self, request):
        """Enhance multiple images"""
        return JsonResponse({
            'batch_id': 'mock-batch-id',
            'status': 'completed',
            'results': [
                {'enhanced_url': 'https://via.placeholder.com/1000x1000/FFFFFF/000000?text=Enhanced+1'},
                {'enhanced_url': 'https://via.placeholder.com/1000x1000/FFFFFF/000000?text=Enhanced+2'},
            ]
        })


@method_decorator(csrf_exempt, name='dispatch')
class AIBlogView(View):
    """API endpoints for blog generation"""
    
    def post(self, request, action=None):
        try:
            if action == 'generate':
                return self.generate(request)
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
        except Exception as e:
            logger.exception("Blog API error")
            return JsonResponse({'error': str(e)}, status=500)
    
    def generate(self, request):
        """Generate blog posts from product data"""
        data = json.loads(request.body) if request.body else {}
        session_data = data.get('session_data', {})
        
        client = OpenRouterFallbackClient()
        blog = BlogService(client)
        
        import asyncio
        result = asyncio.run(blog.generate(session_data))
        
        return JsonResponse({'blogs': result})


@method_decorator(csrf_exempt, name='dispatch')
class AIShoppingView(View):
    """API endpoints for customer shopping assistant"""
    
    def post(self, request, action=None):
        try:
            if action == 'voice':
                return self.voice(request)
            elif action == 'text':
                return self.text(request)
            elif action == 'compare':
                return self.compare(request)
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
        except Exception as e:
            logger.exception("Shopping API error")
            return JsonResponse({'error': str(e)}, status=500)
    
    def voice(self, request):
        """Process voice shopping query"""
        audio_text = request.POST.get('audio_text', '')
        session_id = request.POST.get('session_id')
        context = json.loads(request.POST.get('context', '{}'))
        
        # Mock response for demo
        return JsonResponse({
            'session_id': session_id or 'new-session',
            'intent': 'search',
            'entities': {'category': 'sarees', 'color': 'red', 'price_max': 1000},
            'response_text': 'Found 8 handloom cotton sarees under 1000.',
            'response_audio_url': None,
            'products': [],
            'suggestions': ['Filter by handloom', 'Sort by rating']
        })
    
    def text(self, request):
        """Process text shopping query"""
        data = json.loads(request.body) if request.body else {}
        query = data.get('query', '')
        
        return JsonResponse({
            'intent': 'search',
            'entities': {'category': 'sarees', 'color': 'red', 'price_max': 1000},
            'response_text': f'Found products for: {query}',
            'products': [],
            'suggestions': ['Filter by handloom', 'Sort by rating']
        })
    
    def compare(self, request):
        """Compare products"""
        data = json.loads(request.body) if request.body else {}
        product_ids = data.get('product_ids', [])
        
        return JsonResponse({
            'comparison': {},
            'summary': 'Product comparison',
            'recommendation': product_ids[0] if product_ids else None
        })


@method_decorator(csrf_exempt, name='dispatch')
class AIHealthView(View):
    """Health check endpoint"""
    
    def get(self, request):
        return JsonResponse({
            'status': 'ok',
            'service': 'ai-services',
            'version': '1.0.0',
            'openrouter_configured': bool(getattr(settings, 'AI_API_KEY', ''))
        })