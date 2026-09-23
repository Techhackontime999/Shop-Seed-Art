# ai_services/services/blog.py
import json
import logging
from typing import Dict, Any, List, Optional

from ..clients import OpenRouterFallbackClient

logger = logging.getLogger(__name__)


BLOG_SYSTEM_PROMPT = """You are an expert content marketer for Indian handicrafts e-commerce.
Create engaging, SEO-optimized blog posts that tell the story behind artisan products.
Your posts should educate, inspire, and drive traffic to product pages.

Blog types:
1. STORY - Artisan journey, cultural heritage, origin story
2. HOW_TO - Process, technique, craftsmanship details
3. CARE - Maintenance, cleaning, preservation tips
4. STYLING - Usage ideas, occasions, pairing suggestions
5. GUIDE - Buying guide, selection tips, quality indicators

Tone: Authentic, respectful, informative, slightly premium.
Length: 300-500 words per post (concise, demo-friendly).
SEO: Natural keyword integration, proper headings, meta description."""

BLOG_USER_TEMPLATE = """Create a {blog_type} blog post for this product:

Product Data:
{product_json}

Requirements:
- Type: {blog_type}
- Title: Compelling, SEO-friendly, includes main keyword
- Meta description: 150-160 chars with keyword
- H1: Same as title
- H2/H3: Logical structure
- Keywords: Natural integration of: {keywords}
- Link to product: Natural mention with anchor text
- Tone: Authentic, educational, inspiring

Return JSON:
{response_schema}"""

BLOG_RESPONSE_SCHEMA = """{{
  "title": "Blog Post Title",
  "type": "{blog_type}",
  "meta_description": "SEO meta description",
  "keywords": ["keyword1", "keyword2"],
  "body_html": "<h1>Title</h1><p>Content...</p><h2>Section</h2>...",
  "estimated_read_time": 5,
  "featured_image_suggestion": "Description of ideal featured image",
  "product_mentions": ["How product is referenced naturally"]
}}"""


class BlogService:
    """Service for AI-generated blog posts during product creation"""
    
    def __init__(self, client):
        self.client = client
        self.blog_types = ['story', 'how_to', 'care', 'styling', 'guide']
    
    async def generate(self, session_data: Dict[str, Any]) -> List[Dict]:
        """Generate 3-5 blog posts from product data"""
        
        # Select blog types based on product
        selected_types = self._select_blog_types(session_data)
        
        blogs = []
        for blog_type in selected_types:
            blog = await self._generate_single_blog(session_data, blog_type)
            if blog:
                blogs.append(blog)
        
        return blogs
    
    def _select_blog_types(self, session_data: Dict) -> List[str]:
        """Select appropriate blog types based on product"""
        attrs = session_data.get('attributes', {})
        category = attrs.get('category', '')
        technique = attrs.get('technique', '')
        has_story = bool(attrs.get('origin_story', ''))
        
        types = []
        
        # Always include story if origin story exists
        if has_story:
            types.append('story')
        
        # How-to for handcrafted items
        if technique and 'hand' in technique.lower():
            types.append('how_to')
        
        # Care guide for textiles
        if 'textile' in category or 'fabric' in category:
            types.append('care')
        
        # Styling for wearables
        if category in ['textiles', 'garments', 'jewelry']:
            types.append('styling')
        
        # Default to story if nothing else
        if not types:
            types = ['story', 'care']
        
        return types[:4]  # Max 4 posts
    
    async def _generate_single_blog(self, session_data: Dict, blog_type: str) -> Optional[Dict]:
        """Generate a single blog post"""
        
        # Prepare product summary
        product_summary = {
            'name': self._generate_product_name(session_data),
            'category': session_data.get('attributes', {}).get('category', ''),
            'subcategory': session_data.get('attributes', {}).get('subcategory', ''),
            'material': session_data.get('attributes', {}).get('material', ''),
            'technique': session_data.get('attributes', {}).get('technique', ''),
            'color': session_data.get('attributes', {}).get('color', ''),
            'origin': session_data.get('attributes', {}).get('origin', ''),
            'origin_story': session_data.get('attributes', {}).get('origin_story', ''),
            'care': session_data.get('attributes', {}).get('care', ''),
            'dimensions': session_data.get('attributes', {}).get('dimensions', ''),
            'price': session_data.get('pricing', {}).get('recommended_price', 0),
            'descriptions': session_data.get('descriptions', {}),
        }
        
        keywords = self._extract_keywords(product_summary)
        
        user_prompt = BLOG_USER_TEMPLATE.format(
            blog_type=blog_type,
            product_json=json.dumps(product_summary, indent=2),
            keywords=', '.join(keywords),
            response_schema=BLOG_RESPONSE_SCHEMA.format(blog_type=blog_type),
        )
        
        # Call AI
        response = self._call_blog_ai(blog_type, user_prompt)
        
        if not response.success:
            return self._fallback_blog(blog_type, product_summary)
        
        try:
            result = json.loads(response.data['content'])
            # When the deterministic fallback handled the request, prefer our
            # type-specific fallback so each blog stays distinct and on-type.
            if response.model_used == 'fallback-deterministic':
                raise json.JSONDecodeError('fallback', '', 0)
            result['_meta'] = {
                'model': response.model_used,
                'latency_ms': response.latency_ms,
                'cost_usd': response.cost_usd
            }
            return result
        except json.JSONDecodeError:
            return self._fallback_blog(blog_type, product_summary)
    
    def _extract_keywords(self, product: Dict) -> List[str]:
        """Extract SEO keywords from product data"""
        keywords = []
        
        # Core keywords
        for field in ['material', 'technique', 'subcategory', 'category', 'color']:
            val = product.get(field, '')
            if val:
                keywords.append(val.lower())
        
        # Combinations
        if product.get('material') and product.get('subcategory'):
            keywords.append(f"{product['material']} {product['subcategory']}")
        if product.get('technique') and product.get('subcategory'):
            keywords.append(f"{product['technique']} {product['subcategory']}")
        
        # Remove duplicates, limit
        unique = list(dict.fromkeys(keywords))
        return unique[:10]
    
    def _generate_product_name(self, session_data: Dict) -> str:
        """Generate product name from attributes"""
        attrs = session_data.get('attributes', '')
        parts = []
        for field in ['color', 'material', 'subcategory']:
            val = attrs.get(field, '')
            if val:
                parts.append(val)
        return ' '.join(parts).title() or 'Artisan Product'
    
    def _call_blog_ai(self, blog_type: str, user_prompt: str):
        """Call AI for blog generation"""
        from ..clients import OpenRouterFallbackClient
        
        system_prompt = BLOG_SYSTEM_PROMPT
        client = OpenRouterFallbackClient()
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        return client.chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=600,
            response_format={"type": "json_object"}
        )
    
    def _fallback_blog(self, blog_type: str, product: Dict) -> Dict:
        """Fallback blog content"""
        name = product.get('name', 'Artisan Product')
        
        templates = {
            'story': {
                'title': f'The Story Behind {name}',
                'body': f'<h1>The Story Behind {name}</h1><p>Every {name.lower()} carries a story...</p>'
            },
            'how_to': {
                'title': f'How It\'s Made: {name}',
                'body': f'<h1>How It\'s Made: {name}</h1><p>Our artisans use traditional techniques...</p>'
            },
            'care': {
                'title': f'Care Guide for Your {name}',
                'body': f'<h1>Care Guide for Your {name}</h1><p>Proper care ensures your {name.lower()} lasts for generations...</p>'
            },
            'styling': {
                'title': f'5 Ways to Style Your {name}',
                'body': f'<h1>5 Ways to Style Your {name}</h1><p>Versatile and timeless, the {name.lower()} can be styled...</p>'
            },
            'guide': {
                'title': f'Buying Guide: Choosing the Perfect {product.get("subcategory", "Product")}',
                'body': f'<h1>Buying Guide: Choosing the Perfect {product.get("subcategory", "Product")}</h1><p>When selecting a {product.get("subcategory", "product").lower()}...</p>'
            }
        }
        
        tmpl = templates.get(blog_type, templates['story'])
        
        return {
            'title': tmpl['title'],
            'type': blog_type,
            'meta_description': f'Discover the story and craftsmanship behind {name}.',
            'keywords': self._extract_keywords(product),
            'body_html': tmpl['body'],
            'estimated_read_time': 5,
            'featured_image_suggestion': f'Lifestyle shot of {name} in use',
            'product_mentions': [f'Check out our {name.lower()} collection'],
            '_meta': {'model': 'fallback', 'fallback': True}
        }