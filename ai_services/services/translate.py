# ai_services/services/translate.py
import json
import logging
from typing import Dict, Any

from ..clients import OpenRouterFallbackClient

logger = logging.getLogger(__name__)

TRANSLATE_SYSTEM_PROMPT = """You are a precise translator for an Indian e-commerce seller studio.
Translate the user's text faithfully into the requested target language (en = English, hi = Hindi in Devanagari).
Keep product terms, numbers, prices and measurements intact. Return ONLY the translated text with no quotes, no prefixes."""

TRANSLATE_USER_TEMPLATE = """Translate the following text into {target_name} ({target_code}):

{text}"""

# Small fallback vocabulary for the most common textile/craft terms so a mock
# or offline fallback can still produce a believable Hindi/English result.
_HI_FALLBACK = {
    'cotton': 'कॉटन', 'silk': 'रेशम', 'handloom': 'हैंडलूम', 'saree': 'साड़ी',
    'red': 'लाल', 'blue': 'नीला', 'green': 'हरा', 'yellow': 'पीला', 'black': 'काला',
    'white': 'सफ़ेद', 'sarees': 'साड़ियाँ', 'zari': 'ज़री', 'border': 'बॉर्डर',
    'handcrafted': 'हस्तनिर्मित', 'traditional': 'पारंपरिक', 'premium': 'प्रीमियम',
    'quality': 'गुणवत्ता', 'weaver': 'बुनकर', 'artisan': 'कारीगर', 'fabric': 'कपड़ा',
    'embroidery': 'कढ़ाई', 'kurta': 'कुर्ता', 'dupatta': 'दुपट्टा', 'wooden': 'लकड़ी का',
    'brass': 'पीतल', 'handmade': 'हाथ से बना', 'pure': 'शुद्ध', 'natural': 'प्राकृतिक',
    'meter': 'मीटर', 'long': 'लंबा', 'length': 'लंबाई', 'width': 'चौड़ाई',
}

_EN_FALLBACK = {
    'कॉटन': 'cotton', 'रेशम': 'silk', 'साड़ी': 'saree', 'लाल': 'red', 'नीला': 'blue',
    'हरा': 'green', 'पीला': 'yellow', 'काला': 'black', 'सफ़ेद': 'white',
    'हैंडलूम': 'handloom', 'ज़री': 'zari', 'बॉर्डर': 'border', 'हस्तनिर्मित': 'handcrafted',
    'पारंपरिक': 'traditional', 'प्रीमियम': 'premium', 'गुणवत्ता': 'quality',
    'बुनकर': 'weaver', 'कारीगर': 'artisan', 'कपड़ा': 'fabric', 'कढ़ाई': 'embroidery',
    'कुर्ता': 'kurta', 'दुपट्टा': 'dupatta', 'लकड़ी': 'wood', 'पीतल': 'brass',
    'हस्तशिल्प': 'handicraft', 'मीटर': 'meter', 'लंबा': 'long',
}


class TranslateService:
    """Bilingual English <-> Hindi translation service (with fallback)."""

    LANG_MAP = {'en': ('English', 'en'), 'en-IN': ('English', 'en'),
                'hi': ('Hindi', 'hi'), 'hi-IN': ('Hindi', 'hi')}

    def __init__(self, client: OpenRouterFallbackClient):
        self.client = client

    def translate(self, text: str, target_language: str = 'hi-IN') -> Dict[str, Any]:
        """Translate text into English or Hindi.

        Returns: {'translation': str, 'source_language': str, 'target_language': str,
                  'fallback': bool}
        """
        text = (text or '').strip()
        if not text:
            return {'translation': '', 'source_language': 'unknown',
                    'target_language': target_language, 'fallback': False}

        target = self.LANG_MAP.get(target_language)
        if not target:
            target = self.LANG_MAP.get('hi-IN')
        target_name, target_code = target

        from ..clients import AIResponse

        user_prompt = TRANSLATE_USER_TEMPLATE.format(
            target_name=target_name, target_code=target_code, text=text)
        messages = [
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self.client.chat_completion(
                messages,
                temperature=0.2,
                max_tokens=2000,
            )
        except Exception as e:
            logger.warning(f"Translate AI call failed: {e}")
            response = AIResponse(success=False, error=str(e))

        if response.success:
            content = (response.data or {}).get('content') or ''
            translation = content.strip()
            # Reject the generic fallback echo or an unchanged passthrough so
            # the dictionary fallback produces a real bilingual result.
            is_echo = not translation or 'fallback response for:' in translation.lower() \
                or translation == text
            if not is_echo:
                return {'translation': translation,
                        'source_language': 'hi' if target_code == 'en' else 'en',
                        'target_language': target_language, 'fallback': False}

        return {'translation': self._fallback_translate(text, target_code),
                'source_language': 'hi' if target_code == 'en' else 'en',
                'target_language': target_language, 'fallback': True}

    def _fallback_translate(self, text: str, target_code: str) -> str:
        """Word-for-word dictionary fallback (Hindi persists if already Hindi etc.)."""
        vocab = _HI_FALLBACK if target_code == 'hi' else _EN_FALLBACK
        words = text.split()
        translated = []
        for word in words:
            key = word.strip('.,;:!?"\'()[]').lower()
            mapped = vocab.get(key)
            if mapped:
                translated.append(mapped)
            else:
                translated.append(word)
        return ' '.join(translated)