# ai_services/clients/openrouter.py
import json
import time
import requests
import logging
from typing import Dict, Any, Optional, List
from django.conf import settings
from django.core.cache import cache

from .base import AIAPIClient, AIResponse, AIServiceError

logger = logging.getLogger(__name__)


class OpenRouterClient(AIAPIClient):
    """OpenRouter API client for AI model access"""
    
    def __init__(self, timeout: int = 60, max_retries: int = 3):
        super().__init__(timeout, max_retries)
        self.api_key = getattr(settings, 'AI_API_KEY', None)
        self.base_url = getattr(settings, 'AI_BASE_URL', 'https://openrouter.ai/api/v1')
        self.default_model = getattr(settings, 'AI_MODEL', 'nvidia/nemotron-3-ultra')
        self.provider = getattr(settings, 'AI_PROVIDER', 'auto')
        
        if not self.api_key:
            logger.warning("OpenRouter API key not configured. AI features will use fallback.")
            self.enabled = False
        else:
            self.enabled = True
        
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
            'X-Title': 'Shop-Seed Art',
        })
    
    def _make_request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP request to OpenRouter API"""
        url = f"{self.base_url}{endpoint}"
        
        response = self.session.post(url, json=payload, timeout=self.timeout)
        
        if response.status_code == 401:
            raise AIServiceError("Invalid API key", "AUTH_ERROR")
        elif response.status_code == 429:
            raise AIServiceError("Rate limit exceeded", "RATE_LIMIT")
        elif response.status_code >= 500:
            raise AIServiceError(f"Server error: {response.status_code}", "SERVER_ERROR")
        elif response.status_code >= 400:
            try:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', response.text)
            except:
                error_msg = response.text
            raise AIServiceError(f"API error: {error_msg}", "API_ERROR")
        
        return response.json()
    
    def chat_completion(self, messages: List[Dict[str, str]], 
                        temperature: float = 0.7, max_tokens: int = 2000,
                        model: Optional[str] = None,
                        **kwargs) -> AIResponse:
        """Execute chat completion via OpenRouter"""
        
        if not self.enabled:
            return AIResponse(
                success=False,
                error="OpenRouter API not configured",
                model_used="none"
            )
        
        start_time = time.time()
        
        payload = {
            'model': model or self.default_model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'stream': False,
        }
        
        # Add provider preference if specified
        if self.provider != 'auto':
            payload['provider'] = {'order': [self.provider], 'allow_fallback': True}
        
        # Add any extra parameters
        for key, value in kwargs.items():
            if key not in payload:
                payload[key] = value
        
        try:
            result = self._make_request('/chat/completions', payload)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            choice = result['choices'][0]
            usage = result.get('usage', {})
            
            tokens_used = usage.get('total_tokens', 0)
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            
            model_used = result.get('model', model or self.default_model)
            cost = self._calculate_cost(model_used, prompt_tokens, completion_tokens)
            
            content = choice['message']['content']
            
            return AIResponse(
                success=True,
                data={'content': content, 'finish_reason': choice.get('finish_reason')},
                latency_ms=latency_ms,
                model_used=model_used,
                tokens_used=tokens_used,
                cost_usd=cost
            )
            
        except AIServiceError:
            raise
        except requests.Timeout:
            raise AIServiceError("Request timeout", "TIMEOUT")
        except requests.RequestException as e:
            raise AIServiceError(f"Network error: {str(e)}", "NETWORK_ERROR")
        except Exception as e:
            logger.exception("Unexpected error in chat_completion")
            raise AIServiceError(f"Unexpected error: {str(e)}", "UNKNOWN_ERROR")
    
    def generate_structured(self, system_prompt: str, user_prompt: str,
                            schema: Dict[str, Any], temperature: float = 0.3,
                            model: Optional[str] = None) -> AIResponse:
        """Generate structured JSON output using function calling or prompt engineering"""
        
        # Add schema instruction to system prompt
        schema_instruction = f"""
You must respond with valid JSON matching this exact schema:
{json.dumps(schema, indent=2)}

Rules:
1. Output ONLY the JSON object, no extra text, no markdown, no explanation
2. All required fields must be present
3. Use correct data types (string, number, boolean, array, object)
4. For enums, use exact values from schema
5. If uncertain, use null for optional fields
"""
        
        messages = [
            {"role": "system", "content": system_prompt + schema_instruction},
            {"role": "user", "content": user_prompt}
        ]
        
        # Use lower temperature for structured output
        return self.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=4000,
            model=model,
            response_format={"type": "json_object"}  # OpenRouter supports this
        )
    
    def generate_embeddings(self, texts: List[str], model: str = "text-embedding-3-small") -> AIResponse:
        """Generate embeddings for texts"""
        if not self.enabled:
            return AIResponse(success=False, error="OpenRouter not configured")
        
        payload = {
            'model': model,
            'input': texts
        }
        
        try:
            result = self._make_request('/embeddings', payload)
            embeddings = [item['embedding'] for item in result['data']]
            
            return AIResponse(
                success=True,
                data={'embeddings': embeddings},
                model_used=model
            )
        except Exception as e:
            raise AIServiceError(f"Embedding generation failed: {str(e)}", "EMBEDDING_ERROR")


class OpenRouterFallbackClient(OpenRouterClient):
    """Extended client with deterministic fallback for development"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_fallback = not self.enabled
    
    def chat_completion(self, messages: List[Dict[str, str]], 
                        temperature: float = 0.7, max_tokens: int = 2000,
                        model: Optional[str] = None,
                        **kwargs) -> AIResponse:
        
        if self.use_fallback:
            return self._fallback_response(messages, temperature)
        
        try:
            return super().chat_completion(messages, temperature, max_tokens, model, **kwargs)
        except AIServiceError as e:
            code = e.code
            msg = str(e).lower()
            # Gracefully fall back on transient or quota-related failures so the
            # demo never hard-fails: rate limits, server/network/timeout errors,
            # and free-tier credit/max_tokens limits.
            fallback_codes = ('RATE_LIMIT', 'SERVER_ERROR', 'NETWORK_ERROR', 'TIMEOUT', 'API_ERROR')
            if code in fallback_codes or 'credit' in msg or 'max_tokens' in msg:
                logger.warning(f"OpenRouter error, falling back: {e}")
                return self._fallback_response(messages, temperature)
            raise
    
    def _fallback_response(self, messages: List[Dict[str, str]], 
                           temperature: float) -> AIResponse:
        """Deterministic fallback for development/testing"""
        user_content = messages[-1]['content'] if messages else ""
        
        # Simple keyword-based routing for demo
        content_lower = user_content.lower()
        
        if 'blog' in content_lower or 'blog post' in content_lower or 'meta_description' in content_lower:
            return AIResponse(
                success=True,
                data={
                    'content': json.dumps({
                        'title': 'The Story Behind Handcrafted Indian Textiles',
                        'type': 'story',
                        'meta_description': 'Discover the craftsmanship and heritage of handcrafted Indian textiles.',
                        'keywords': ['handloom', 'indian textiles', 'artisan'],
                        'body_html': '<h1>The Story Behind Handcrafted Indian Textiles</h1><p>Each piece begins with a tradition passed down through generations.</p>',
                        'estimated_read_time': 4,
                        'featured_image_suggestion': 'Artisan at loom in natural light',
                        'product_mentions': ['Explore our handloom collection']
                    }),
                    'finish_reason': 'stop'
                },
                latency_ms=80,
                model_used='fallback-deterministic',
                cost_usd=0.0
            )

        if 'catalog' in content_lower or 'product' in content_lower or 'describe' in content_lower:
            return AIResponse(
                success=True,
                data={
                    'content': json.dumps({
                        'attributes': {
                            'category': 'textiles',
                            'subcategory': 'sarees',
                            'material': 'cotton',
                            'technique': 'handloom',
                            'color': 'red',
                            'dimensions': '5.5m x 1.1m',
                            'care': 'dry clean only',
                            'occasion': 'office, formal'
                        },
                        'descriptions': {
                            'en': 'Elegant red handloom cotton saree with zari border, perfect for office wear.',
                            'hi': 'जरी बॉर्डर वाली सुंदर लाल हैंडलूम कॉटन साड़ी, ऑफिस वियर के लिए उत्तम।'
                        },
                        'seo_tags': ['handloom cotton saree', 'red saree', 'office wear'],
                        'suggested_category': 'textiles > sarees',
                        'confidence': 0.92
                    }),
                    'finish_reason': 'stop'
                },
                latency_ms=100,
                model_used='fallback-deterministic',
                cost_usd=0.0
            )
        
        elif 'price' in content_lower or 'pricing' in content_lower:
            return AIResponse(
                success=True,
                data={
                    'content': json.dumps({
                        'floor_price': 450,
                        'recommended_price': 799,
                        'premium_price': 1199,
                        'confidence': 0.87,
                        'reasoning': [
                            'Similar handloom cotton sarees sell at 650-950',
                            'Raw cotton cost up 12% this quarter',
                            'Festival season demand +15%'
                        ],
                        'cost_breakdown': {'material': 280, 'labor': 120, 'overhead': 50}
                    }),
                    'finish_reason': 'stop'
                },
                latency_ms=100,
                model_used='fallback-deterministic',
                cost_usd=0.0
            )
        
        # Default fallback
        return AIResponse(
            success=True,
            data={'content': f"Fallback response for: {user_content[:100]}"},
            latency_ms=50,
            model_used='fallback-deterministic',
            cost_usd=0.0
        )