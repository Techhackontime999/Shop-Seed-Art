"""Where the catalog decides a listing belongs.

The seller can dictate or type a product that belongs anywhere in the shop's
tree, so the placement has to come back as a real category and a real
subcategory of *that* category. These tests are about the resolution rules:
the seller's own pick beats the model's, a hallucinated name is dropped rather
than created, and a subcategory never leaks across departments.
"""

import json
from unittest import mock

from django.test import TestCase

from shop.models import Category, SubCategory

from .services.voice_text import generate_product_catalog


def reply(**fields):
    """A model reply shaped the way the catalog prompt asks for."""
    body = {
        'title': 'Hand Painted Madhubani Panel',
        'description': 'A village scene painted by hand in Mithila style.',
        'keywords': ['madhubani', 'wall art'],
        'category': 'Paintings & Wall Art',
        'subcategory': 'Madhubani',
    }
    body.update(fields)
    return json.dumps(body)


class CatalogPlacementTests(TestCase):
    def setUp(self):
        self.paintings = Category.objects.create(
            name='Paintings & Wall Art', slug='paintings')
        self.madhubani = SubCategory.objects.create(
            category=self.paintings, name='Madhubani', slug='madhubani')
        self.kitchen = Category.objects.create(
            name='Home & Kitchen', slug='kitchen')
        SubCategory.objects.create(
            category=self.kitchen, name='Cookware', slug='cookware')

    def generate(self, model_reply, **product_data):
        payload = {'title': 'a hand painted village scene'}
        payload.update(product_data)
        with mock.patch(
            'ai_services.services.voice_text.text_completion',
            return_value={'text': model_reply, 'model': 'stub'},
        ):
            return generate_product_catalog(payload)

    # ── the model's own answer ──────────────────────────────────────
    def test_a_correct_placement_is_returned(self):
        result = self.generate(reply())
        self.assertEqual(result['category'], 'Paintings & Wall Art')
        self.assertEqual(result['subcategory'], 'Madhubani')

    def test_the_model_answers_with_a_seeded_artisan_department(self):
        """The project ships an artisan taxonomy, so the seeded department and
        its own subcategory must resolve like any other real pair."""
        result = self.generate(reply(category='Paintings & Folk Art',
                                     subcategory='Madhubani'))
        self.assertEqual(result['category'], 'Paintings & Folk Art')
        self.assertEqual(result['subcategory'], 'Madhubani')

    def test_a_department_the_shop_does_not_have_is_dropped(self):
        """The model invents departments. None may reach the database."""
        before = Category.objects.count()
        result = self.generate(reply(category='Home Decor'))
        self.assertNotEqual(result['category'], 'Home Decor')
        # Counted as a delta: the project seeds an artisan taxonomy, so the
        # database is never empty when this runs. What matters is that this
        # call invented nothing.
        self.assertEqual(Category.objects.count(), before)

    def test_a_subcategory_from_another_department_is_dropped(self):
        result = self.generate(reply(subcategory='Cookware'))
        self.assertEqual(result['category'], 'Paintings & Wall Art')
        self.assertNotEqual(result['subcategory'], 'Cookware')

    def test_a_missing_subcategory_is_guessed_from_the_words(self):
        result = self.generate(reply(subcategory='', description=(
            'A hand painted madhubani village scene for the wall.')))
        self.assertEqual(result['subcategory'], 'Madhubani')

    def test_nothing_is_guessed_when_the_words_do_not_match(self):
        """A wrong pre-selection is worse than an empty picker: the seller
        is shown a choice that looks deliberate. The department still has to
        be something real, so it falls back rather than inventing."""
        result = self.generate(
            reply(category='', subcategory='', title='Cotton Scarf',
                  description='Woven on a hand loom, finished with a knotted '
                              'fringe. Soft enough for everyday wear.'),
            title='a plain cotton scarf woven on a hand loom',
            seller_notes='a plain cotton scarf woven on a hand loom')
        # Real department, not necessarily one of this test's own two: the
        # seeded artisan taxonomy is in the database too, so "did not invent a
        # department" is the claim under test, not "picked a fixture".
        self.assertIn(result['category'],
                      set(Category.objects.values_list('name', flat=True)))
        self.assertEqual(result['subcategory'], '')

    # ── the seller's own pick ───────────────────────────────────────
    def test_the_seller_selection_beats_the_model(self):
        """They looked at the list of departments; the model did not."""
        result = self.generate(
            reply(category='Paintings & Wall Art', subcategory='Madhubani'),
            category='Home & Kitchen')
        self.assertEqual(result['category'], 'Home & Kitchen')

    def test_the_sellers_subcategory_beats_the_model(self):
        result = self.generate(
            reply(subcategory='Madhubani'),
            category='Home & Kitchen', subcategory='Cookware')
        self.assertEqual(result['category'], 'Home & Kitchen')
        self.assertEqual(result['subcategory'], 'Cookware')

    def test_a_stale_seller_subcategory_does_not_pull_the_category_away(self):
        """The picker can still hold yesterday's subcategory. It must be
        dropped, not allowed to pick the department for the seller."""
        result = self.generate(
            reply(),
            category='Home & Kitchen', subcategory='Madhubani')
        self.assertEqual(result['category'], 'Home & Kitchen')
        self.assertEqual(result['subcategory'], '')

    # ── the prompt itself ───────────────────────────────────────────
    def test_the_model_is_given_the_exact_names_to_choose_from(self):
        """The allowed set belongs to the system prompt: it is a rule about
        the answer, not a fact the seller supplied, and it must not be the
        first thing pushed off the end of a long description."""
        with mock.patch(
            'ai_services.services.voice_text.text_completion',
            return_value={'text': reply(), 'model': 'stub'},
        ) as call:
            generate_product_catalog({'title': 'a village scene'})
        system_prompt = call.call_args[1]['system_prompt']
        self.assertIn('Paintings & Wall Art', system_prompt)
        self.assertIn('Madhubani', system_prompt)
        self.assertIn('Home & Kitchen', system_prompt)
        # Each subcategory sits under its own department, so the pair is
        # unambiguous without a second pass.
        line = [l for l in system_prompt.splitlines()
                if 'Madhubani' in l][0]
        # The line pairs Madhubani with whichever department owns it, so the
        # seeded Paintings & Folk Art is just as valid here as the fixture's.
        owners = {s.category.name for s in
                 SubCategory.objects.filter(name='Madhubani')}
        self.assertTrue(
            any(owner in line for owner in owners),
            'Madhubani line %r names none of its departments %r'
            % (line, sorted(owners)))

    def test_nothing_is_invented_when_the_shop_has_no_taxonomy(self):
        Category.objects.all().delete()
        result = self.generate(reply())
        self.assertEqual(result['category'], '')
        self.assertEqual(result['subcategory'], '')
        self.assertEqual(Category.objects.count(), 0)
