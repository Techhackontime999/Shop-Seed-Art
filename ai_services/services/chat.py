# ai_services/services/chat.py
"""Guided conversational assistant for product listing creation.

The service turns a free-form seller conversation (typed or spoken, any Indian
language) into structured catalog data. It runs a deterministic state machine
so the chat always responds instantly (no API dependency), while a best-effort
OpenRouter call can polish the reply wording when credits are available.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..clients import OpenRouterFallbackClient

logger = logging.getLogger(__name__)

COLORS = {
    'red': ['red', 'laal', 'lal'],
    'blue': ['blue', 'neela', 'nila'],
    'green': ['green', 'hara', 'hari'],
    'yellow': ['yellow', 'peela', 'pila'],
    'black': ['black', 'kala', 'kali', 'kaali'],
    'white': ['white', 'safed', 'shwet'],
    'orange': ['orange', 'narangi'],
    'pink': ['pink', 'gulabi'],
    'purple': ['purple', 'purple rang', 'baingani'],
    'grey': ['grey', 'gray', 'slameti'],
    'brown': ['brown', 'bhura', 'bhoora'],
    'golden': ['golden', 'gold', 'sona', 'suna'],
    'silver': ['silver', 'chandi', 'rupa'],
    'maroon': ['maroon', 'majroon', 'jamevani'],
    'navy': ['navy', 'navy blue'],
    'teal': ['teal'],
    'beige': ['beige'],
    'cream': ['cream', 'malai'],
    'mustard': ['mustard', 'sarsa'],
}

MATERIALS = {
    'cotton': ['cotton', 'kapaas', 'sutti'],
    'silk': ['silk', 'reshm', 'pat'],
    'wool': ['wool', 'oon'],
    'jute': ['jute', 'pat', 'gunny'],
    'pashmina': ['pashmina', 'pashm'],
    'brass': ['brass', 'pitl', 'kansa'],
    'copper': ['copper', 'tamba'],
    'clay': ['clay', 'mitti', 'terracotta'],
    'wood': ['wood', 'lakdi', 'sheesham'],
    'leather': ['leather', 'chamra'],
    'bamboo': ['bamboo', 'bans'],
    'beads': ['beads', 'moti', 'kundan'],
    'velvet': ['velvet', 'maquhal'],
    'linen': ['linen'],
    'polyester': ['polyester', 'polyster'],
}

TECHNIQUES = {
    'handloom': ['handloom', 'hand loom', 'hanikargha'],
    'handwoven': ['handwoven', 'hand woven'],
    'handblock': ['handblock', 'hand block', 'block print', 'bagh', 'ajrakh'],
    'embroidered': ['embroider', 'kadhai', 'chikankari', 'phulkari', 'zardozi'],
    'bandhani': ['bandhani', 'bandhej'],
    'ikat': ['ikat', 'ikhat'],
    'kalamkari': ['kalamkari'],
    'madhubani': ['madhubani'],
    'warli': ['warli'],
    'mirrorwork': ['mirror work', 'shisha'],
    'macrame': ['macrame'],
    'knitted': ['knit'],
    'carved': ['carved', 'carving', 'nakkashi'],
    'copperplate': ['copper plate'],
    'galvanized': ['galvanized'],
    'filigree': ['filigree'],
    'batik': ['batik'],
    'tie-dye': ['tie dye', 'bandhej'],
}

SUB_CATEGORIES = {
    'sarees': ['saree', 'saari', 'sari'],
    'fabrics': ['fabric', 'cloth', 'yard', 'kapda'],
    'kurta': ['kurta', 'kurti', 'kurta set'],
    'dress': ['dress', 'gown', 'lehenga', 'ghagra'],
    'dupatta': ['dupatta', 'stole', 'scarf'],
    'jacket': ['jacket', 'blazer', 'nehru'],
    'necklaces': ['necklace', 'haar', 'mangalsutra', 'choker'],
    'earrings': ['earring', 'jhumka', 'bali'],
    'bracelets': ['bracelet', 'kada', 'bangle', 'chudi'],
    'pots': ['pot', 'vase', 'kalash', 'matki', 'gada'],
    'decor': ['decor', 'showpiece', 'diyas', 'hanging', 'wall art', 'toran'],
    'baskets': ['basket', 'tokri', 'dali'],
    'lamps': ['lamp', 'diyas', 'lantern', 'kandil'],
    'bags': ['bag', 'tote', 'potli', 'jhola', 'pouch'],
    'bedding': ['quilt', 'razai', 'bedsheet', 'pillow', 'cushion'],
    'rugs': ['rug', 'carpet', 'durrie', 'dhurrie', 'gadda'],
    'shoes': ['footwear', 'juttis', 'kolhapuri', 'sandal'],
    'toys': ['toy', 'doll', 'puppet', 'khilona'],
    'paintings': ['painting', 'pichwai', 'canvas', 'print'],
}


def _match_keywords(text: str, mapping: Dict[str, List[str]]) -> List[str]:
    out = []
    lowered = text.lower()
    for key, words in mapping.items():
        for w in words:
            if re.search(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', lowered):
                out.append(key)
                break
    return out


def _parse_message(text: str, session: Dict[str, Any], accumulate: bool = True) -> Dict[str, Any]:
    """Best-effort extraction of product clues from a free-form message."""
    lowered = text.lower()
    attrs = session.setdefault('attributes', {})

    for color_name, words in COLORS.items():
        if any(re.search(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', lowered) for w in words):
            if 'color' not in attrs:
                attrs['color'] = color_name
            break

    materials = _match_keywords(lowered, MATERIALS)
    if materials and 'material' not in attrs:
        attrs['material'] = materials[0]

    techniques = _match_keywords(lowered, TECHNIQUES)
    if techniques and 'technique' not in attrs:
        attrs['technique'] = techniques[0]

    for sub, words in SUB_CATEGORIES.items():
        if any(re.search(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', lowered) for w in words):
            attrs['subcategory'] = sub
            break

    price = re.search(r'(?:rs\.?|rupees?|₹|\u20b9)\s*(\d{2,6})', text, re.IGNORECASE) \
        or re.search(r'(\d{2,6})\s*(?:rs\.?|rupees?)', text, re.IGNORECASE)
    if price:
        session['price_hint'] = int(price.group(1))

    if 'dimensions' not in attrs:
        dim = re.search(r'(\d+(?:\.\d+)?\s*(?:m|meter|metre|cm|inch|inches|ft))\s*(?:x|×|by)\s*(\d+(?:\.\d+)?\s*(?:m|cm|inch|ft))', lowered)
        if dim:
            attrs['dimensions'] = f"{dim.group(1)} x {dim.group(2)}"

    if 'care' not in attrs and re.search(r'wash|dry clean|hand wash|machine wash', lowered):
        if 'dry clean' in lowered:
            attrs['care'] = 'dry clean only'
        else:
            attrs['care'] = 'gentle hand wash'

    if 'occasion' not in attrs and re.search(r'wedding|festival|office|casual|artisan|puja', lowered):
        occasion = 'wedding' if 'wedding' in lowered else 'festival' if 'festival' in lowered \
            else 'office' if 'office' in lowered else 'casual'
        attrs['occasion'] = occasion

    # Keep a running description the seller has provided (multilingual friendly)
    if accumulate:
        session['raw_description'] = ((session.get('raw_description') or '') + ' ' + text).strip()[:1200]

    return attrs


def _summarize(session: Dict[str, Any]) -> str:
    attrs = session.get('attributes', {})
    bits = []

    def add(label, value):
        if value:
            bits.append(f"{label}: {value}")

    add('Type', attrs.get('subcategory', attrs.get('category')))
    add('Color', attrs.get('color'))
    add('Material', attrs.get('material'))
    add('Technique', attrs.get('technique'))
    add('Dimensions', attrs.get('dimensions'))
    add('Care', attrs.get('care'))
    if attrs.get('occasion'):
        add('Occasion', attrs.get('occasion'))
    if session.get('price_hint'):
        bits.append(f"Price idea: ₹{session['price_hint']}")

    if not bits:
        return "I don't have the details yet."
    return 'You told me — ' + ' · '.join(bits) + '.'


class ChatService:
    """Interactive guided listing assistant (stateless per call)."""

    STAGE_GREETING = 'greeting'
    STAGE_COLLECTING = 'collecting'
    STAGE_PRICE = 'price'
    STAGE_READY = 'ready'

    def __init__(self, client: OpenRouterFallbackClient):
        self.client = client

    async def process(self, message: str, language: str = 'en-IN',
                      session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle one user turn and return assistant reply + updated state.

        Expected reply payload:
          reply          friendly assistant text (caller-controlled language)
          session        updated session data (attributes, raw_description…)
          stage          one of the STAGE_* values
          ready          True when enough info to build the listing
          missing        short hint of what's still needed (for UI chips)
        """
        session = dict(session or {})
        session.setdefault('attributes', {})
        session.setdefault('messages', [])

        text = (message or '').strip()
        lowered = text.lower()
        session['messages'].append(text)

        # Handle greetings / smalltalk / explicit intent
        greeting = bool(re.match(r'^(hi|hello|hey|namaste|namaskar|hii+|hola|yo)\b', lowered))
        build_intent = any(k in lowered for k in ['build', 'create listing', 'make listing', 'fill form',
                                                  'ready', 'banao', 'banaiye', 'yes build', 'generate'])
        restart_intent = any(k in lowered for k in ['start over', 'restart', 'reset', 'shuru se', 'naya'])

        if restart_intent:
            session = {'attributes': {}, 'messages': session.get('messages', [])}
            return self._reply('Okay, let’s start fresh. What are you creating or selling today?',
                               session, self.STAGE_COLLECTING, ready=False)

        if build_intent and 'price_hint' in session:
            ready = self._is_ready(session)
            if ready:
                return self._reply(
                    'Perfect — I have everything I need. Let’s build your listing!',
                    session, self.STAGE_READY, ready=True)
            return self._still_missing_reply(session)

        if greeting and not session.get('attributes') and 'raw_description' not in session:
            return self._reply(
                'Namaste! 👋 I’m your AI listing assistant. Tell me what you create or sell — '
                'you can type it or just speak into the mic. Any language works!',
                session, self.STAGE_COLLECTING, ready=False)

        # A price-only message (e.g. "around 800 rupees") shouldn't pollute the
        # running product description, but the price hint itself is captured.
        price_mention = re.search(r'(?:rs\.?|rupees?|₹|\u20b9)\s*(\d{2,6})', text, re.IGNORECASE) \
            or re.search(r'(\d{2,6})\s*(?:rs\.?|rupees?)', text, re.IGNORECASE)
        is_price_only = price_mention and len(text.split()) <= 6

        _parse_message(text, session, accumulate=not is_price_only)

        # Decide the stage based on how much we now know.
        if 'price_hint' not in session:
            return self._still_missing_reply(session, ask_price_first=True)

        ready = self._is_ready(session)
        if ready:
            summary = _summarize(session)
            return self._reply(
                f"Got it! {summary}\n\nTap “Build my listing” and I’ll fill the form — "
                'you can also keep telling me more (photos, story, care tips).',
                session, self.STAGE_READY, ready=True)

        return self._still_missing_reply(session)

    # ------------------------------------------------------------------ utils
    def _is_ready(self, session: Dict[str, Any]) -> bool:
        attrs = session.get('attributes', {})
        has_type = bool(attrs.get('subcategory') or attrs.get('category'))
        has_material = bool(attrs.get('material'))
        has_price = 'price_hint' in session
        return has_type and has_material and has_price

    def _still_missing_reply(self, session: Dict[str, Any],
                             ask_price_first: bool = False,
                             state: Optional[str] = None) -> Dict[str, Any]:
        attrs = session.get('attributes', {})

        if ask_price_first or 'price_hint' not in session:
            summary = _summarize(session)
            if summary.endswith('.'):
                summary = summary[:-1]
            return self._reply(
                f"{summary} What price do you have in mind? (example: “₹900” or “about 800 rupees”)",
                session, self.STAGE_PRICE, ready=False,
                missing='price')

        missing = []
        if not (attrs.get('subcategory') or attrs.get('category')):
            missing.append('what kind of product it is')
        if not attrs.get('material'):
            missing.append('the material')
        if not attrs.get('color'):
            missing.append('the color')
        if not (attrs.get('technique') or attrs.get('care') or attrs.get('occasion')):
            missing.append('a special detail (craft, care or occasion)')

        if not missing:
            return self._reply(
                f"{_summarize(session)} That’s a strong start — tap “Build my listing” to continue!",
                session, self.STAGE_READY, ready=True)

        prompt = 'You can also mention a few more things:' if not ask_price_first else \
            'Describe a little more — for example:'
        question_map = {
            'what kind of product it is': 'What exactly is it — a saree, kurta, vase, necklace…?',
            'the material': 'What is it made of — cotton, silk, brass, wood…?',
            'the color': 'What color is it?',
            'a special detail (craft, care or occasion)':
                'Any special detail? (handloom, handwoven, dry-clean only, festival wear…)',
            'price': 'What price do you have in mind? (e.g. ₹900)',
        }
        questions = [question_map.get(m, m) for m in missing]
        reply = f"{_summarize(session)}\n\n{prompt}\n\n" + ' '.join('→ ' + q for q in questions)
        return self._reply(reply, session, self.STAGE_COLLECTING, ready=False,
                           missing=missing)

    def _reply(self, text: str, session: Dict[str, Any], stage: str,
               ready: bool, missing: Any = None) -> Dict[str, Any]:
        return {
            'reply': text,
            'session': session,
            'stage': stage,
            'ready': ready,
            'missing': missing,
        }