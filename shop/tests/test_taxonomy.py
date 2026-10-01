"""Tests for the shop's category tree helper.

Every caller -- the AI Studio pickers, the catalog placement and the publish
endpoint -- resolves names through this module, so these tests are about the
one rule that matters: a name that is not in the database is reported, never
created.
"""

from django.test import TestCase

from shop.models import Category, Product, SubCategory
from shop.taxonomy import (
    category_choices,
    find_category,
    find_subcategory,
    suggest_category,
    suggest_subcategory,
)


class FindCategoryTests(TestCase):
    def setUp(self):
        self.kitchen = Category.objects.create(name='Home & Kitchen', slug='kitchen')
        self.books = Category.objects.create(name='Books', slug='books')

    def test_finds_a_category_exactly(self):
        self.assertEqual(find_category('Books'), self.books)

    def test_ignores_case_and_surrounding_space(self):
        self.assertEqual(find_category('  books  '), self.books)

    def test_treats_ampersand_and_and_as_the_same_word(self):
        """The AI writes "Home and Kitchen" as readily as "Home & Kitchen"."""
        self.assertEqual(find_category('Home and Kitchen'), self.kitchen)
        self.assertEqual(find_category('Home & Kitchen'), self.kitchen)

    def test_an_invented_name_is_not_created(self):
        before = Category.objects.count()
        self.assertIsNone(find_category('Home Decor'))
        # Counted as a delta, not an absolute: the project seeds an artisan
        # taxonomy, so the database is never empty when this runs.
        self.assertEqual(Category.objects.count(), before)

    def test_a_suggestion_is_only_made_when_the_words_point_somewhere(self):
        """No overlap means no suggestion. A wrong guess the seller can see is
        harmless; a confident one is not, so silence beats a coin toss."""
        self.assertIsNone(suggest_category(''))
        self.assertIsNone(suggest_category('qwertyuiop'))
        self.assertEqual(suggest_category('a kitchen knife'), self.kitchen)
        # Matching is literal word overlap, not inference: "novel" is not in
        # the word "Books", so it suggests nothing rather than guessing.
        self.assertIsNone(suggest_category('a novel for the bedside'))
        self.assertEqual(suggest_category('a book for the bedside'), self.books)

    def test_subcategory_words_are_evidence_for_their_department(self):
        madhubani = Category.objects.create(
            name='Paintings & Wall Art', slug='paintings')
        # "Kalighat" rather than a real seeded subcategory: the project ships an
        # artisan taxonomy that already contains Madhubani, and this test is
        # about the matching rule, not about which department happens to win.
        SubCategory.objects.create(
            category=madhubani, name='Kalighat', slug='kalighat')
        self.assertEqual(
            suggest_category('a hand painted kalighat scroll'), madhubani)

    def test_the_caller_supplies_the_fallback(self):
        self.assertEqual(suggest_category('qwertyuiop', default=self.books),
                         self.books)


class FindSubcategoryTests(TestCase):
    def setUp(self):
        self.kitchen = Category.objects.create(name='Home & Kitchen', slug='kitchen')
        self.fashion = Category.objects.create(name='Fashion', slug='fashion')
        self.decor = SubCategory.objects.create(
            category=self.kitchen, name='Home Decor', slug='home-decor')
        self.saree = SubCategory.objects.create(
            category=self.fashion, name='Sarees', slug='sarees')

    def test_finds_a_subcategory_inside_its_own_department(self):
        self.assertEqual(find_subcategory('home decor', self.kitchen), self.decor)

    def test_a_real_name_in_the_wrong_department_is_refused(self):
        """The name exists, but not here -- that is still a mismatch."""
        self.assertIsNone(find_subcategory('Sarees', self.kitchen))

    def test_a_never_seen_name_is_refused(self):
        self.assertIsNone(find_subcategory('Canvas', self.kitchen))

    def test_two_departments_may_share_a_subcategory_name(self):
        other = SubCategory.objects.create(
            category=self.fashion, name='Home Decor', slug='fashion-home-decor')
        self.assertEqual(find_subcategory('Home Decor', self.kitchen), self.decor)
        self.assertEqual(find_subcategory('Home Decor', self.fashion), other)


class SuggestSubcategoryTests(TestCase):
    def setUp(self):
        self.paintings = Category.objects.create(
            name='Paintings & Wall Art', slug='paintings')
        self.madhubani = SubCategory.objects.create(
            category=self.paintings, name='Madhubani', slug='madhubani')
        self.canvas = SubCategory.objects.create(
            category=self.paintings, name='Canvas & Prints', slug='canvas')
        self.kitchen = Category.objects.create(name='Kitchen', slug='kitchen')
        SubCategory.objects.create(
            category=self.kitchen, name='Cookware', slug='cookware')

    def test_matches_on_the_words_that_are_there(self):
        self.assertEqual(
            suggest_subcategory('a hand painted madhubani painting',
                                self.paintings),
            self.madhubani)

    def test_a_subcategory_never_leaves_its_department(self):
        guess = suggest_subcategory('a pair of cookware pots', self.paintings)
        self.assertIsNone(guess)

    def test_nothing_is_offered_when_the_words_do_not_match(self):
        """Returning the first subcategory alphabetically would file a
        Madhubani painting under whatever happens to sort first."""
        self.assertIsNone(
            suggest_subcategory('a hand painted village scene', self.paintings))

    def test_nothing_is_offered_for_empty_text(self):
        self.assertIsNone(suggest_subcategory('', self.paintings))
        self.assertIsNone(suggest_subcategory(None, self.paintings))

    def test_no_department_is_no_answer(self):
        self.assertIsNone(suggest_subcategory('madhubani', None))


class CategoryChoicesTests(TestCase):
    def setUp(self):
        self.kitchen = Category.objects.create(name='Home & Kitchen', slug='kitchen')
        self.decor = SubCategory.objects.create(
            category=self.kitchen, name='Home Decor', slug='home-decor')
        self.empty = Category.objects.create(name='Security', slug='security')
        SubCategory.objects.create(
            category=self.empty, name='CCTV', slug='cctv')
        self.live = self.make_product(
            'Live Tray', self.kitchen, price='1200', available=True)
        self.draft = self.make_product(
            'Draft Tray', self.kitchen, price='900', available=False)
        self.sheffield = self.make_product(
            'Sharp Knife', self.kitchen, price='2400', available=True)

    def seller(self):
        """One seller for the whole class: the price maths is about what the
        shop sells, not about who sells it."""
        if not hasattr(self, '_seller'):
            from django.contrib.auth import get_user_model
            from accounts.models import SellerProfile
            user = get_user_model().objects.create_user(
                'tax_seller', 't@example.com', 'pw')
            self._seller = SellerProfile.objects.create(
                user=user, shop_name='T', bank_account='1',
                account_holder_name='T', ifsc_code='H', phone='9', address='a',
                is_email_verified=True, is_phone_verified=True)
        return self._seller

    def make_product(self, name, category, price, available):
        return Product.objects.create(
            seller=self.seller(), name=name, category=category,
            description='A thing for sale.', price=price, stock=1,
            available=available, subcategory=self.decor
            if category is self.kitchen else None,
        )

    def entry(self, name):
        for row in category_choices():
            if row['name'] == name:
                return row
        self.fail('no category_choices row for %s' % name)

    def test_returns_every_category_in_the_shop(self):
        self.assertEqual(
            {row['name'] for row in category_choices()},
            set(Category.objects.values_list('name', flat=True)))

    def test_counts_splits_live_products_from_drafts(self):
        row = self.entry('Home & Kitchen')
        self.assertEqual(row['live'], 2)
        self.assertEqual(row['drafts'], 1)

    def test_the_average_ignores_drafts(self):
        """A draft has never been priced by the market, so it must not drag
        the suggestion down."""
        row = self.entry('Home & Kitchen')
        self.assertEqual(row['avg_price'], 1800)
        self.assertEqual(row['price_low'], 1200)
        self.assertEqual(row['price_high'], 2400)

    def test_a_department_with_nothing_listed_has_no_suggestion(self):
        row = self.entry('Security')
        self.assertEqual(row['live'], 0)
        self.assertIsNone(row['avg_price'])
        self.assertIsNone(row['price_low'])
        self.assertIsNone(row['price_high'])

    def test_subcategories_come_with_their_own_counts(self):
        subs = {s['name']: s for s in self.entry('Home & Kitchen')['subcategories']}
        self.assertEqual(set(subs), {'Home Decor'})
        self.assertEqual(subs['Home Decor']['live'], 2)
        self.assertEqual(subs['Home Decor']['avg_price'], 1800)

    def test_prices_are_plain_numbers_so_json_can_carry_them(self):
        row = self.entry('Home & Kitchen')
        self.assertIsInstance(row['avg_price'], int)
        import json
        json.dumps(category_choices())

    def test_a_subcategory_without_products_is_still_offered(self):
        subs = {s['name'] for s in self.entry('Security')['subcategories']}
        self.assertEqual(subs, {'CCTV'})
