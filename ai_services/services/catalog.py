# ai_services/services/catalog.py
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from ..clients import OpenRouterFallbackClient, AIResponse
from ..clients.base import AIServiceError

logger = logging.getLogger(__name__)


# Catalog prompts
CATALOG_SYSTEM_PROMPT = """You are an expert e-commerce cataloger for Indian handicrafts and textiles.
Your task is to extract structured product attributes from natural language descriptions
and generate professional, SEO-optimized product descriptions in English and Hindi.

You specialize in: textiles (sarees, fabrics, garments), handicrafts, jewelry, pottery, home decor.
You understand regional techniques: handloom, khaddar, bandhani, ikat, kalamkari, chikankari, etc.
You know materials: cotton, silk, wool, jute, pashmina, brass, copper, clay, wood, leather."""

CATALOG_USER_TEMPLATE = """Analyze this product description and extract structured attributes:

Input: "{text}"
Language: {language}
Category hint: {category_hint}

Return JSON with these fields:
{{
  "attributes": {{
    "category": "main category (textiles/handicrafts/jewelry/pottery/home_decor)",
    "subcategory": "specific type (sarees/fabrics/garments/necklaces/etc)",
    "material": "primary material (cotton/silk/wool/brass/clay/etc)",
    "technique": "craft technique (handloom/handwoven/handblock/embroidered/etc)",
    "color": "primary color",
    "colors": ["array of colors"],
    "dimensions": "size/dimensions with units",
    "weight": "weight with units",
    "care": "care instructions",
    "occasion": "suitable occasions",
    "origin": "region/origin if mentioned",
    "origin_story": "artisan story or cultural significance",
    "features": ["key features"],
    "tags": ["searchable tags"]
  }},
  "descriptions": {{
    "en": "Professional English description (150-300 words, SEO-optimized)",
    "hi": "Professional Hindi description in Devanagari (150-300 words)",
    "original": "{text}"
  }},
  "seo_tags": ["5-10 searchable tags"],
  "suggested_category": "category > subcategory",
  "confidence": 0.95
}}"""

REFINE_SYSTEM_PROMPT = """You are refining a product catalog entry based on seller corrections.
Preserve all correct information, only update what the seller explicitly changed.
Return the complete corrected JSON."""


class CatalogService:
    """Service for multilingual product cataloging"""
    
    def __init__(self, client: OpenRouterFallbackClient):
        self.client = client
    
    async def process_text(self, text: str, language: str = 'en-IN', 
                          category_hint: Optional[str] = None) -> Dict[str, Any]:
        """Process natural language text into structured catalog data"""
        
        # Check cache
        cache_key = self._cache_key(text, language)
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        # Build prompt
        user_prompt = CATALOG_USER_TEMPLATE.format(
            text=text,
            language=language,
            category_hint=category_hint or 'auto-detect'
        )
        
        # Call AI
        response = self._call_ai_with_retry(
            CATALOG_SYSTEM_PROMPT,
            user_prompt,
            language=language
        )
        
        if not response.success:
            return self._fallback_catalog(text, language)
        
        # Parse and validate
        try:
            result = json.loads(response.data['content'])
            result = self._validate_and_clean(result)
            result['_meta'] = {
                'model': response.model_used,
                'latency_ms': response.latency_ms,
                'cost_usd': response.cost_usd
            }
            
            # Cache result
            self._set_cache(cache_key, result)
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse catalog response: {e}")
            return self._fallback_catalog(text, language)
    
    async def process_voice(self, audio_text: str, language: str = 'hi-IN',
                           category_hint: Optional[str] = None) -> Dict[str, Any]:
        """Process transcribed voice text"""
        return await self.process_text(audio_text, language, category_hint)
    
    async def refine(self, original: Dict, corrections: Dict) -> Dict[str, Any]:
        """Refine catalog data based on seller corrections"""
        user_prompt = f"""Original data: {json.dumps(original)}
Seller corrections: {json.dumps(corrections)}

Return complete corrected JSON."""
        
        response = self._call_ai_with_retry(
            REFINE_SYSTEM_PROMPT,
            user_prompt
        )
        
        if response.success:
            try:
                return json.loads(response.data['content'])
            except:
                pass
        return original
    
    def _call_ai_with_retry(self, system: str, user: str, language: str = 'en-IN',
                           max_retries: int = 2) -> 'AIResponse':
        """Call AI with retries"""
        from ..clients import OpenRouterFallbackClient
        
        client = OpenRouterFallbackClient()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        
        for attempt in range(max_retries + 1):
            try:
                response = client.chat_completion(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1800,
                    response_format={"type": "json_object"}
                )
                if response.success:
                    return response
            except Exception as e:
                logger.warning(f"Catalog AI attempt {attempt + 1} failed: {e}")
                if attempt == max_retries:
                    raise
        
        raise Exception("Failed to generate catalog after retries")
    
    def _validate_and_clean(self, data: Dict) -> Dict:
        """Validate and clean catalog data"""
        # Ensure required fields
        defaults = {
            'attributes': {},
            'descriptions': {'en': '', 'hi': '', 'original': ''},
            'seo_tags': [],
            'suggested_category': 'general',
            'confidence': 0.5
        }
        
        for key, default in defaults.items():
            if key not in data:
                data[key] = default
            elif isinstance(default, dict):
                for k, v in default.items():
                    if k not in data[key]:
                        data[key][k] = v
        
        # Ensure descriptions exist
        if not data['descriptions'].get('en'):
            data['descriptions']['en'] = data['descriptions'].get('original', '')
        if not data['descriptions'].get('hi'):
            data['descriptions']['hi'] = data['descriptions'].get('original', '')
        
        # Clean SEO tags
        if isinstance(data.get('seo_tags'), list):
            data['seo_tags'] = [str(t).strip() for t in data['seo_tags'] if str(t).strip()][:15]
        else:
            data['seo_tags'] = []
        
        # Confidence bounds
        data['confidence'] = max(0.0, min(1.0, float(data.get('confidence', 0.5))))
        
        return data
    
    def _fallback_catalog(self, text: str, language: str) -> Dict:
        """Fallback catalog for when AI fails"""
        is_hindi = language.startswith('hi')
        return {
            'attributes': {
                'category': 'textiles',
                'subcategory': 'sarees' if 'saree' in text.lower() or 'साड़ी' in text else 'fabric',
                'material': 'cotton' if 'cotton' in text.lower() or 'कॉटन' in text else 'silk',
                'technique': 'handloom' if 'handloom' in text.lower() or 'हैंडलूम' in text else 'machine',
                'color': 'red' if 'red' in text.lower() or 'लाल' in text else 'blue',
                'dimensions': '5.5m x 1.1m',
                'weight': '300g',
                'care': 'dry clean only',
                'occasion': 'office, formal',
                'origin_story': 'Handcrafted by artisans using traditional techniques.',
                'features': ['handcrafted', 'traditional', 'premium quality'],
                'tags': ['handloom', 'cotton', 'saree', 'traditional']
            },
            'descriptions': {
                'en': f"Premium handcrafted product: {text[:200]}",
                'hi': f"प्रीमियम हस्तशिल्प उत्पाद: {text[:200]}",
                'original': text
            },
            'seo_tags': ['handcrafted', 'traditional', 'premium'],
            'suggested_category': 'textiles > sarees',
            'confidence': 0.7,
            '_meta': {'model': 'fallback', 'fallback': True}
        }
    
    def _cache_key(self, text: str, language: str) -> str:
        import hashlib
        key = f"catalog:{language}:{text[:500]}"
        return f"catalog:{hashlib.sha256(key.encode()).hexdigest()[:16]}"
    
    def _get_cached(self, key: str) -> Optional[Dict]:
        from django.core.cache import cache
        return cache.get(key)
    
    def _set_cache(self, key: str, value: Dict, ttl: int = 86400):
        from django.core.cache import cache
        cache.set(key, value, ttl)