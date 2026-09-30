"""Seed the second level of the taxonomy for the existing categories.

The AI Studio can only offer a subcategory list that exists, and until this
ran there were none, so the pickers would have been empty on a live database.
The names below are ordinary merchandising choices for a marketplace of this
kind; admins can rename or delete any of them from the Category admin, and the
studio reads whatever is in the table at request time.

Idempotent by (category, name): re-running adds nothing and changes nothing.
"""

from django.db import migrations
from django.utils.text import slugify

SUBCATEGORIES = {
    'Electronics': [
        'Mobile Phones', 'Laptops & Computers', 'Audio', 'Cameras',
        'Smart Home', 'Wearables', 'Accessories',
    ],
    'Fashion': [
        "Women's Clothing", "Men's Clothing", 'Kids Clothing', 'Footwear',
        'Bags & Luggage', 'Jewellery', 'Ethnic Wear',
    ],
    'Home & Kitchen': [
        'Cookware', 'Kitchen Appliances', 'Home Decor', 'Furniture',
        'Lighting', 'Storage', 'Dining & Serveware',
    ],
    'Books': [
        'Fiction', 'Non-Fiction', "Children's Books", 'Academic',
        'Comics & Graphic Novels', 'Self-Help',
    ],
    'Beauty': [
        'Skincare', 'Haircare', 'Makeup', 'Fragrance',
        "Men's Grooming", 'Bath & Body',
    ],
    'Sports': [
        'Fitness', 'Team Sports', 'Outdoor & Camping', 'Cycling',
        'Yoga', 'Sportswear',
    ],
    'Toys & Games': [
        'Educational Toys', 'Board Games', 'Soft Toys', 'Ride-Ons',
        'Puzzles', 'Arts & Crafts',
    ],
    'Automotive': [
        'Car Care', 'Car Accessories', 'Bike Accessories',
        'Tools & Equipment', 'Tyres & Parts',
    ],
    'Home Textiles': [
        'Bedsheets', 'Curtains', 'Towels', 'Carpets & Rugs',
        'Cushions & Covers',
    ],
    'Security': [
        'CCTV & Cameras', 'Alarms & Sensors', 'Smart Locks',
        'Fire Safety', 'Personal Safety',
    ],
    'Paintings & Wall Art': [
        'Madhubani Art', 'Wall Hangings', 'Framed Art', 'Canvas & Prints',
    ],
}


def seed(apps, schema_editor):
    Category = apps.get_model('shop', 'Category')
    SubCategory = apps.get_model('shop', 'SubCategory')
    db_alias = schema_editor.connection.alias

    for category_name, names in SUBCATEGORIES.items():
        category = Category.objects.using(db_alias).filter(
            name=category_name).first()
        if category is None:
            # The category does not exist in this database (a fresh install or
            # a test fixture). Skipping is correct: seeding the taxonomy must
            # never invent a department.
            continue
        for name in names:
            SubCategory.objects.using(db_alias).get_or_create(
                category=category, name=name,
                defaults={'slug': slugify(name)[:200]},
            )


def unseed(apps, schema_editor):
    SubCategory = apps.get_model('shop', 'SubCategory')
    db_alias = schema_editor.connection.alias
    for category_name, names in SUBCATEGORIES.items():
        SubCategory.objects.using(db_alias).filter(
            category__name=category_name, name__in=names,
        ).delete()


class Migration(migrations.Migration):

    dependencies = [('shop', '0007_subcategory_product_subcategory')]

    operations = [migrations.RunPython(seed, unseed)]
