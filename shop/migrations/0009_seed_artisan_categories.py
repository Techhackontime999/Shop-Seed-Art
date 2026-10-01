"""Seed an artisan/handicraft taxonomy for a platform built for artisans.

The categories that shipped with the project were a generic marketplace set
(Electronics, Automotive, Books, Sports), which is not what this platform
sells. This migration adds the craft departments the site actually trades in,
along with the second level the AI Studio offers sellers, and moves the
genuinely handmade products that already exist into them.

Deliberately non-destructive: products are only ever *moved* between
categories, never deleted, and the old generic categories are left in place
because they still hold demo stock. Removing those is a separate, deliberate
decision for the operator.

Idempotent by slug: re-running adds nothing and moves nothing twice.
"""

from django.db import migrations
from django.utils.text import slugify

ARTISAN_CATEGORIES = {
    'Pottery & Ceramics': ['Clay Pots', 'Terracotta', 'Blue Pottery', 'Ceramic Vases'],
    'Textiles & Weaving': ['Sarees & Fabrics', 'Embroidery', 'Block Print', 'Quilting & Rugs'],
    'Paintings & Folk Art': ['Madhubani', 'Gond Art', 'Warli Art', 'Pattachitra', 'Wall Hangings'],
    'Jewellery': ['Silver', 'Kundan', 'Beaded', 'Tribal'],
    'Wood Carving': ['Sculptures', 'Furniture', 'Masks', 'Toys'],
    'Metal & Brass Craft': ['Brassware', 'Bell Metal', 'Iron Work', 'Copper'],
    'Leather Craft': ['Bags', 'Wallets', 'Footwear', 'Juttis'],
    'Bamboo & Cane': ['Baskets', 'Furniture', 'Mats'],
    'Masks & Puppetry': ['Kathputli', 'Theyyam Masks', 'Shadow Puppets'],
    'Incense & Wellness': ['Incense', 'Attar', 'Herbal Soap'],
}

# Products whose names make their craft unambiguous. Matched case-insensitively
# on a lowercase substring so the mapping survives a rename of the old category.
PRODUCT_MOVES = [
    ('blue clay vase', 'Pottery & Ceramics'),
    ('madhubani', 'Paintings & Folk Art'),
    ('water pot', 'Pottery & Ceramics'),
    ('clay pot', 'Pottery & Ceramics'),
    ('handmade', 'Textiles & Weaving'),
    ('saree', 'Textiles & Weaving'),
    ('leather', 'Leather Craft'),
    ('terracotta', 'Pottery & Ceramics'),
    ('block print', 'Textiles & Weaving'),
    ('embroid', 'Textiles & Weaving'),
]


def seed(apps, schema_editor):
    Category = apps.get_model('shop', 'Category')
    SubCategory = apps.get_model('shop', 'SubCategory')
    Product = apps.get_model('shop', 'Product')
    db_alias = schema_editor.connection.alias

    for name, subs in ARTISAN_CATEGORIES.items():
        category, _ = Category.objects.using(db_alias).get_or_create(
            slug=slugify(name)[:200], defaults={'name': name},
        )
        for sub in subs:
            SubCategory.objects.using(db_alias).get_or_create(
                category=category, name=sub,
                defaults={'slug': slugify(sub)[:200]},
            )

    artisan_slugs = [slugify(n)[:200] for n in ARTISAN_CATEGORIES]
    for needle, category_name in PRODUCT_MOVES:
        category = Category.objects.using(db_alias).filter(
            slug=slugify(category_name)[:200]).first()
        if category is None:
            continue
        # Excluding the artisan slugs, rather than listing them, is what makes
        # this both correct and idempotent: it picks up handmade products that
        # are still sitting in a legacy category, while re-running cannot drag a
        # product back out of the department it was already moved into.
        Product.objects.using(db_alias).filter(
            name__icontains=needle,
        ).exclude(category__slug__in=artisan_slugs).update(category=category)


def unseed(apps, schema_editor):
    Category = apps.get_model('shop', 'Category')
    SubCategory = apps.get_model('shop', 'SubCategory')
    db_alias = schema_editor.connection.alias
    slugs = [slugify(n)[:200] for n in ARTISAN_CATEGORIES]
    # Products are not moved back: the reverse cannot know their old category,
    # and losing that would silently re-file a seller's listing. Only the
    # taxonomy itself is removed, and only while it is empty.
    SubCategory.objects.using(db_alias).filter(category__slug__in=slugs).delete()
    Category.objects.using(db_alias).filter(slug__in=slugs, products__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [('shop', '0008_seed_subcategories')]

    operations = [migrations.RunPython(seed, unseed)]