# shop/taxonomy.py
"""The one place that knows the shop's category tree.

The AI Studio, the seller product form and the publish endpoint all have to
agree on which categories exist. When each of them carried its own list, the
studio shipped a hardcoded one ("Home Decor", "Textiles", "Jewellery") that
matched nothing in the database, and publishing silently *created* a category
row for whatever name arrived. A seller's typo became a new department.

So: resolve against the database, always, and fail loudly instead of
inventing a row.
"""

from django.db.models import Avg, Count, Max, Min, Q

from .models import Category, SubCategory


def _clean_price(value):
    """The average price as a plain rupee number, or ``None``.

    SQLite hands back a ``Decimal``; it has to survive JSON, and a product with
    no price yet should not produce a suggestion of zero.
    """
    if value is None:
        return None
    value = int(round(float(value)))
    return value if value > 0 else None


def _significant(text):
    """The words in ``text`` worth matching on.

    "a", "of", "and" carry no signal about what a listing is, and treating
    them as evidence is how a description of anything ends up matching every
    category equally.
    """
    return {w for w in text.replace('/', ' ').split() if len(w) > 2}


def _stems(word):
    """The forms of ``word`` worth comparing, to fold away plurals.

    A seller writes "a book" and the department is called "Books"; matching on
    exact words only, "book" scores nothing and the picker offers no help on
    the single most obvious case there is.
    """
    forms = {word}
    if len(word) > 3 and word.endswith('s'):
        forms.add(word[:-1])
    if len(word) > 4 and word.endswith('es'):
        forms.add(word[:-2])
    return forms


def _stem_set(words):
    folded = set()
    for word in words:
        folded |= _stems(word)
    return folded


def category_choices():
    """Every category with its subcategories and live price stats.

    Returns ``[{'id', 'name', 'slug', 'live', 'drafts', 'avg_price',
    'price_low', 'price_high', 'subcategories': [{'id', 'name', 'live',
    'avg_price'}]}]``.

    The studio's pickers and its price suggestion both come from here, so the
    departments a seller can choose are the departments that exist, and the
    suggested price is derived from what the shop already sells rather than
    from a table written next to the script.
    """
    live = Q(products__available=True)
    categories = Category.objects.annotate(
        live_count=Count('products', filter=live, distinct=True),
        all_count=Count('products', distinct=True),
        avg_price=Avg('products__price', filter=live),
        price_low=Min('products__price', filter=live),
        price_high=Max('products__price', filter=live),
    ).order_by('name')

    subs = SubCategory.objects.annotate(
        live_count=Count('products', filter=Q(products__available=True),
                         distinct=True),
        avg_price=Avg('products__price', filter=Q(products__available=True)),
    ).order_by('category__name', 'name')

    by_category = {}
    for sub in subs:
        by_category.setdefault(sub.category_id, []).append(sub)

    tree = []
    for category in categories:
        tree.append({
            'id': category.pk,
            'name': category.name,
            'slug': category.slug,
            'live': category.live_count,
            'drafts': max(category.all_count - category.live_count, 0),
            'avg_price': _clean_price(category.avg_price),
            'price_low': _clean_price(category.price_low),
            'price_high': _clean_price(category.price_high),
            'subcategories': [
                {
                    'id': sub.pk,
                    'name': sub.name,
                    'live': sub.live_count,
                    'avg_price': _clean_price(sub.avg_price),
                }
                for sub in by_category.get(category.pk, [])
            ],
        })
    return tree


def _norm(value):
    """Compare category names the way a human would type them."""
    return ' '.join((value or '').split()).casefold()


def find_category(name):
    """The Category matching ``name``, or ``None``.

    Matching is case- and whitespace-insensitive, and also tolerates the
    ``&``/``and`` difference (``Home & Kitchen`` vs ``Home and Kitchen``) that
    makes an exact match fail for no good reason.
    """
    wanted = _norm(name)
    if not wanted:
        return None
    categories = list(Category.objects.all())
    for category in categories:
        if _norm(category.name) == wanted:
            return category
    folded = wanted.replace('&', 'and')
    for category in categories:
        if _norm(category.name).replace('&', 'and') == folded:
            return category
    return None


def find_subcategory(name, category=None):
    """The SubCategory matching ``name``, optionally restricted to a category.

    The category check matters: "Bedsheets" under Home Textiles must not be
    accepted for a product filed under Electronics.
    """
    wanted = _norm(name)
    if not wanted:
        return None
    queryset = SubCategory.objects.all()
    if category is not None:
        queryset = queryset.filter(category=category)
    for sub in queryset:
        if _norm(sub.name) == wanted:
            return sub
    return None


def suggest_category(facts_text, default=None):
    """Best-effort guess at a category from free text.

    Used only to pre-select the studio's picker so the seller has less typing
    to do; the seller still confirms it, and publish re-validates. Matching is
    deliberately simple (word overlap, then a substring pass) because a wrong
    suggestion the seller can see is harmless, whereas a silent wrong category
    on a live listing is not.
    """
    text = _norm(facts_text)
    if not text:
        return None
    words = _stem_set(_significant(text))

    best = None
    best_score = 0
    for category in Category.objects.all():
        label_words = set(_norm(category.name).split())
        score = len(words & _stem_set(label_words)) * 2
        for word in _stem_set(label_words):
            if len(word) > 3 and word in text:
                score += 1
        # Subcategory names are good evidence too: "Madhubani painting" points
        # at Paintings & Wall Art even though those words are not in the
        # category name itself.
        for sub in category.subcategories.all():
            sub_words = set(_norm(sub.name).split())
            score += len(words & _stem_set(sub_words))
        if score > best_score:
            best, best_score = category, score

    if best is not None:
        return best
    return default


def suggest_subcategory(text, category):
    """Best subcategory of ``category`` for free text, or ``None``.

    Subcategories are optional in the studio, so ``None`` is a perfectly good
    answer and is what the caller gets unless the words genuinely match one.
    Returning the first subcategory alphabetically instead would confidently
    file a "Madhubani painting" under, say, "Curtains".
    """
    if category is None:
        return None
    words = _stem_set(_significant(_norm(text)))
    if not words:
        return None

    best = None
    best_score = 0
    for sub in category.subcategories.all():
        label_words = set(_norm(sub.name).split())
        score = len(words & _stem_set(label_words)) * 2
        for word in _stem_set(label_words):
            if len(word) > 3 and word in words:
                score += 1
        if score > best_score:
            best, best_score = sub, score
    return best
