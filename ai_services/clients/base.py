# ai_services/clients/base.py
import json
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


@dataclass
class AIResponse:
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: int = 0
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None


class AIAPIClient(ABC):
    """Abstract base class for AI API clients"""
    
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = None
    
    @abstractmethod
    def chat_completion(self, messages: List[Dict[str, str]], 
                        temperature: float = 0.7, max_tokens: int = 2000,
                        **kwargs) -> AIResponse:
        """Execute chat completion request"""
        pass
    
    @abstractmethod
    def generate_structured(self, system_prompt: str, user_prompt: str,
                            schema: Dict[str, Any], temperature: float = 0.3) -> AIResponse:
        """Generate structured JSON output"""
        pass
    
    def _get_cache_key(self, prefix: str, *args) -> str:
        """Generate cache key from arguments"""
        import hashlib
        key_data = f"{prefix}:{':'.join(str(a) for a in args)}"
        return f"ai_cache:{hashlib.sha256(key_data.encode()).hexdigest()[:16]}"
    
    def _get_cached(self, cache_key: str) -> Optional[AIResponse]:
        """Get cached response if available"""
        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for {cache_key}")
            return AIResponse(**cached)
        return None
    
    def _set_cache(self, cache_key: str, response: AIResponse, ttl: int = 3600):
        """Cache response"""
        cache.set(cache_key, {
            'success': response.success,
            'data': response.data,
            'error': response.error,
            'latency_ms': response.latency_ms,
            'model_used': response.model_used,
            'tokens_used': response.tokens_used,
            'cost_usd': response.cost_usd,
        }, timeout=ttl)
    
    def _with_retry(self, func, *args, **kwargs) -> AIResponse:
        """Execute with exponential backoff retry"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) * 0.5
                    logger.warning(f"AI request failed (attempt {attempt + 1}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"AI request failed after {self.max_retries} attempts: {e}")
        return AIResponse(success=False, error=str(last_error))
    
    def _build_messages(self, system_prompt: str, user_prompt: str, 
                        history: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        """Build messages array for chat completion"""
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})
        return messages
    
    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate approximate cost in USD"""
        # OpenRouter pricing (approximate per 1M tokens)
        pricing = {
            'nvidia/nemotron-3-ultra': {'input': 0.15, 'output': 0.60},
            'anthropic/claude-3.5-sonnet': {'input': 3.00, 'output': 15.00},
            'anthropic/claude-3-haiku': {'input': 0.25, 'output': 1.25},
            'openai/gpt-4o': {'input': 5.00, 'output': 15.00},
            'openai/gpt-4o-mini': {'input': 0.15, 'output': 0.60},
            'google/gemini-pro': {'input': 0.50, 'output': 1.50},
            'meta-llama/llama-3.1-70b': {'input': 0.90, 'output': 0.90},
        }
        
        model_key = model.lower()
        for key in pricing:
            if key in model_key:
                rates = pricing[key]
                return (prompt_tokens * rates['input'] + completion_tokens * rates['output']) / 1_000_000
        
        # Default fallback
        return (prompt_tokens * 0.50 + completion_tokens * 1.50) / 1_000_000


class AIServiceError(Exception):
    """Custom exception for AI service errors"""
    def __init__(self, message: str, code: str = "AI_ERROR", details: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}