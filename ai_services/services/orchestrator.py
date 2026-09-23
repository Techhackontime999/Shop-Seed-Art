# ai_services/services/orchestrator.py
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from django.conf import settings

from ..clients import OpenRouterFallbackClient
from .catalog import CatalogService
from .image import ImageService
from .pricing import PricingService
from .blog import BlogService

logger = logging.getLogger(__name__)


@dataclass
class ProductCreationSession:
    """Session data for product creation flow"""
    seller_id: int
    mode: str = 'form'  # form, text, voice, ai_assist
    status: str = 'draft'  # draft, processing, preview, completed
    
    # Input data
    voice_text: Optional[str] = None
    text_input: Optional[str] = None
    form_data: Dict[str, Any] = field(default_factory=dict)
    
    # API Results
    catalog_result: Optional[Dict] = None
    enhanced_images: List[Dict] = field(default_factory=list)
    pricing_result: Optional[Dict] = None
    blog_drafts: List[Dict] = field(default_factory=list)
    
    # Metadata
    created_at: str = ''
    updated_at: str = ''
    metadata: Dict = field(default_factory=dict)


class AIOrchestrator:
    """High-level orchestrator for AI-powered product creation"""
    
    def __init__(self):
        self.client = OpenRouterFallbackClient()
        self.catalog = CatalogService(self.client)
        self.image = ImageService(self.client)
        self.pricing = PricingService(self.client)
        self.blog = BlogService(self.client)
    
    async def process_text_input(self, text: str, language: str = 'en-IN') -> Dict[str, Any]:
        """Process natural language text into structured product data"""
        return await self.catalog.process_text(text, language)
    
    async def process_voice_input(self, audio_text: str, language: str = 'hi-IN') -> Dict[str, Any]:
        """Process transcribed voice text into structured product data"""
        return await self.catalog.process_text(audio_text, language)
    
    async def enhance_product_images(self, image_files: List, preset: str = 'auto') -> List[Dict]:
        """Enhance multiple product images"""
        return await self.image.enhance_batch(image_files, preset)
    
    async def suggest_price(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get AI price suggestion"""
        return await self.pricing.analyze(product_data)
    
    async def generate_launch_blogs(self, session_data: Dict[str, Any]) -> List[Dict]:
        """Generate launch blog posts from product data"""
        return await self.blog.generate(session_data)
    
    async def create_complete_product(self, session: ProductCreationSession) -> Dict[str, Any]:
        """Orchestrate complete product creation from session"""
        results = {}
        
        # Step 1: Process input (voice/text/form)
        if session.mode == 'voice' and session.voice_text:
            results['catalog'] = await self.process_voice_input(session.voice_text)
        elif session.mode == 'text' and session.text_input:
            results['catalog'] = await self.process_text_input(session.text_input)
        else:
            # Form mode - use form data directly
            results['catalog'] = self._form_to_catalog(session.form_data)
        
        # Step 2: Enhance images
        if session.form_data.get('images'):
            results['images'] = await self.enhance_product_images(
                session.form_data['images'],
                session.form_data.get('preset', 'auto')
            )
        
        # Step 3: Get pricing
        product_for_pricing = {
            'images': [img['enhanced_url'] for img in results.get('images', [])],
            'description': results['catalog'].get('descriptions', {}).get('en', ''),
            'category': results['catalog'].get('suggested_category', ''),
            'attributes': results['catalog'].get('attributes', {})
        }
        results['pricing'] = await self.suggest_price(product_for_pricing)
        
        # Step 4: Generate blogs
        combined_data = {**results['catalog'], **results}
        results['blogs'] = await self.generate_launch_blogs(combined_data)
        
        return results
    
    def _form_to_catalog(self, form_data: Dict) -> Dict[str, Any]:
        """Convert form data to catalog format"""
        return {
            'attributes': {
                'category': form_data.get('category', ''),
                'material': form_data.get('material', ''),
                'color': form_data.get('color', ''),
                'technique': form_data.get('technique', ''),
                'dimensions': form_data.get('dimensions', ''),
            },
            'descriptions': {
                'en': form_data.get('description', ''),
                'hi': form_data.get('description_hi', ''),
            },
            'seo_tags': form_data.get('tags', []),
            'suggested_category': form_data.get('category', ''),
            'confidence': 1.0
        }


# Singleton instance
_orchestrator = None

def get_orchestrator() -> AIOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AIOrchestrator()
    return _orchestrator