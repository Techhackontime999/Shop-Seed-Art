# ai_services/services/pricing.py
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from ..clients import OpenRouterFallbackClient

logger = logging.getLogger(__name__)


PRICING_SYSTEM_PROMPT = """You are an expert pricing analyst for Indian handicrafts and textiles e-commerce.
Your task is to analyze product data and recommend optimal pricing based on:
1. Material costs (cotton, silk, wool, metals, clay, etc.)
2. Labor intensity (handloom vs machine, embroidery complexity)
3. Market comparables (GeM, Amazon, Flipkart, niche marketplaces)
4. Seasonal demand (festival seasons, wedding season, export cycles)
5. Regional premiums (Varanasi, Kanchipuram, Bhagalpur, etc.)
6. Platform commissions (10-15% typical)
7. Seller margins (target 30-50% above cost)

You have access to current market data and raw material price indices."""

PRICING_USER_TEMPLATE = """Analyze this product and recommend optimal pricing:

Product Data:
{product_json}

Provide pricing analysis in this JSON format:
{{
  "floor_price": 450,
  "recommended_price": 799,
  "premium_price": 1199,
  "currency": "INR",
  "confidence": 0.87,
  "reasoning": [
    "Specific reason 1 with data point",
    "Specific reason 2 with data point",
    "Specific reason 3 with data point"
  ],
  "cost_breakdown": {{
    "material": 280,
    "labor": 120,
    "overhead": 50,
    "platform_commission": 80,
    "packaging": 20
  }},
  "comparables": [
    {{"title": "Similar product", "price": 850, "source": "GeM", "similarity": 0.89}},
    {{"title": "Another similar", "price": 720, "source": "Amazon", "similarity": 0.76}}
  ],
  "market_trends": {{
    "demand_direction": "increasing",
    "seasonal_factor": 1.15,
    "material_cost_trend": "rising"
  }},
  "margin_analysis": {{
    "target_margin_pct": 40,
    "actual_margin_pct": 38,
    "recommended_action": "maintain"
  }}
}}"""

FEEDBACK_SYSTEM_PROMPT = """You are learning from seller pricing feedback.
The seller accepted/rejected/modified your suggestion.
Use this to improve future recommendations."""


@dataclass
class PricingResult:
    floor_price: int
    recommended_price: int
    premium_price: int
    currency: str = "INR"
    confidence: float = 0.0
    reasoning: List[str] = None
    cost_breakdown: Dict = None
    comparables: List[Dict] = None
    market_trends: Dict = None
    margin_analysis: Dict = None
    model_used: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0


class PricingService:
    """Service for AI-powered dynamic pricing"""
    
    def __init__(self, client):
        self.client = client
    
    async def analyze(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze product and recommend pricing"""
        
        # Build product summary for prompt
        product_summary = {
            'category': product_data.get('category', ''),
            'subcategory': product_data.get('subcategory', ''),
            'material': product_data.get('attributes', {}).get('material', ''),
            'technique': product_data.get('attributes', {}).get('technique', ''),
            'dimensions': product_data.get('attributes', {}).get('dimensions', ''),
            'origin': product_data.get('attributes', {}).get('origin', ''),
            'description': product_data.get('description', '')[:500],
            'image_count': len(product_data.get('images', [])),
        }
        
        user_prompt = PRICING_USER_TEMPLATE.format(
            product_json=json.dumps(product_summary, indent=2)
        )
        
        # Call AI
        response = self._call_pricing_ai(
            PRICING_SYSTEM_PROMPT,
            user_prompt
        )
        
        if not response.success:
            return self._fallback_pricing(product_summary)
        
        try:
            result = json.loads(response.data['content'])
            result['_meta'] = {
                'model': response.model_used,
                'latency_ms': response.latency_ms,
                'cost_usd': response.cost_usd
            }
            return self._validate_pricing(result)
        except json.JSONDecodeError:
            return self._fallback_pricing(product_summary)
    
    async def process_feedback(self, product_id: str, suggested_price: int,
                              action: str, final_price: int, notes: str) -> Dict:
        """Process seller feedback on price suggestion"""
        feedback_data = {
            'product_id': product_id,
            'suggested_price': suggested_price,
            'action': action,  # accepted, rejected, modified
            'final_price': final_price,
            'notes': notes
        }
        
        # Store feedback for model improvement
        # In production: save to database for retraining
        logger.info(f"Pricing feedback: {feedback_data}")
        
        return {'status': 'recorded', 'message': 'Feedback will improve future suggestions'}
    
    def _call_pricing_ai(self, system: str, user: str):
        """Call AI for pricing analysis"""
        from ..clients import OpenRouterFallbackClient
        client = OpenRouterFallbackClient()
        
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        
        return client.chat_completion(
            messages=messages,
            temperature=0.3,
            max_tokens=1200,
            response_format={"type": "json_object"}
        )
    
    def _validate_pricing(self, data: Dict) -> Dict:
        """Validate and sanitize pricing result"""
        # Ensure floor <= recommended <= premium
        floor = max(1, int(data.get('floor_price', 100)))
        recommended = max(floor, int(data.get('recommended_price', floor * 2)))
        premium = max(recommended, int(data.get('premium_price', recommended * 1.5)))
        
        # Bounds checking
        if premium > recommended * 5:
            premium = recommended * 2
        
        return {
            'floor_price': floor,
            'recommended_price': recommended,
            'premium_price': premium,
            'currency': data.get('currency', 'INR'),
            'confidence': max(0.0, min(1.0, float(data.get('confidence', 0.5)))),
            'reasoning': data.get('reasoning', ['Based on market analysis']),
            'cost_breakdown': data.get('cost_breakdown', {}),
            'comparables': data.get('comparables', []),
            'market_trends': data.get('market_trends', {}),
            'margin_analysis': data.get('margin_analysis', {}),
        }
    
    def _fallback_pricing(self, product_summary: Dict) -> Dict:
        """Fallback pricing when AI fails"""
        # Simple cost-based pricing
        base_cost = 200
        
        # Adjust for material
        material = product_summary.get('material', '').lower()
        if 'silk' in material:
            base_cost *= 3
        elif 'wool' in material:
            base_cost *= 2
        elif 'cotton' in material:
            base_cost *= 1.2
        
        # Adjust for technique
        technique = product_summary.get('technique', '').lower()
        if 'handloom' in technique or 'hand' in technique:
            base_cost *= 1.5
        elif 'embroider' in technique:
            base_cost *= 1.8
        
        floor = int(base_cost * 1.2)
        recommended = int(base_cost * 2.0)
        premium = int(base_cost * 3.0)
        
        return {
            'floor_price': floor,
            'recommended_price': recommended,
            'premium_price': premium,
            'currency': 'INR',
            'confidence': 0.6,
            'reasoning': [
                f'Cost-based pricing for {product_summary.get("material", "product")}',
                f'{product_summary.get("technique", "Standard")} technique premium applied',
                'Conservative estimate without market data'
            ],
            'cost_breakdown': {
                'material': int(base_cost * 0.5),
                'labor': int(base_cost * 0.3),
                'overhead': int(base_cost * 0.2),
            },
            'comparables': [],
            'market_trends': {'demand_direction': 'stable', 'seasonal_factor': 1.0},
            'margin_analysis': {'target_margin_pct': 40, 'recommended_action': 'review'},
            '_meta': {'model': 'fallback', 'fallback': True}
        }