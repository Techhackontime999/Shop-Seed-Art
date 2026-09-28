import re
from html import unescape

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import SellerProfile
from shop.models import Category, Product


class TestViews(TestCase):

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='fastfood', slug='fastfood1',)
        self.product = Product.objects.create(category=self.category, id=20, name='testproduct', slug='testproduct',
        description='my test product', image='static/core/img/logo.png', price=30)

    def test_product_list_view(self):
        response = self.client.get(reverse('shop:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'shop/product/list.html')

    def test_product_list_by_category_view(self):
        response = self.client.get(reverse('shop:product_list_by_category', kwargs={"category_slug": "fastfood1"}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'shop/product/list.html')

    def test_product_detail_view(self):
        response = self.client.get(reverse('shop:product_detail', kwargs={'id': 20, 'slug': 'testproduct'}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'shop/product/detail.html')
        self.assertContains(response, 'rel="canonical"')

    def test_category_list_has_canonical(self):
        response = self.client.get(reverse('shop:product_list_by_category', kwargs={"category_slug": "fastfood1"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rel="canonical"')

    def test_product_detail_view_error(self):
        response = self.client.get(reverse('shop:product_detail', kwargs={'id': 21, 'slug': 'nottestproduct'}))
        self.assertEqual(response.status_code, 404)

    def test_sitemap_includes_products_and_categories(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/shop/20/testproduct/')
        self.assertContains(response, '/shop/fastfood1/')

    def test_search_suggestions_returns_products_and_categories(self):
        response = self.client.get(reverse('shop:search_suggestions'), {'q': 'testprod'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['query'], 'testprod')
        self.assertTrue(any(p['name'] == 'testproduct' for p in data['products']))
        product = next(p for p in data['products'] if p['name'] == 'testproduct')
        self.assertIn('/shop/20/testproduct/', product['url'])
        self.assertIn('price', product)

        response = self.client.get(reverse('shop:search_suggestions'), {'q': 'fastfood'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(any(c['name'] == 'fastfood' for c in data['categories']))

    def test_search_suggestions_empty_query_returns_empty(self):
        response = self.client.get(reverse('shop:search_suggestions'), {'q': ''})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['products'], [])
        self.assertEqual(data['categories'], [])

    def test_search_suggestions_empty_results(self):
        response = self.client.get(reverse('shop:search_suggestions'), {'q': 'zzzzznope'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['products'], [])

    def test_search_suggestions_caps_limit(self):
        response = self.client.get(reverse('shop:search_suggestions'), {'q': 'test', 'limit': '999'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertLessEqual(len(data['products']), 10)

    def test_search_suggest_api_endpoint_returns_json(self):
        response = self.client.get('/api/search/suggest/', {'q': 'testprod'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'].startswith('application/json'), True)
        data = response.json()
        self.assertEqual(data['query'], 'testprod')
        self.assertTrue(any(p['name'] == 'testproduct' for p in data['products']))
        self.assertIn('image', data['products'][0])
        self.assertIn('price', data['products'][0])

    def test_navbar_includes_autocomplete_markup(self):
        response = self.client.get(reverse('shop:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-search-autocomplete')
        self.assertContains(response, 'data-search-suggest-url')
        self.assertContains(response, '/api/search/suggest/')

    def test_home_renders_scroll_hero(self):
        response = self.client.get(reverse('shop:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-hero-video')
        self.assertContains(response, 'hero-video-suggestions')

    def test_home_renders_scroll_video_hero_when_configured(self):
        from platform_studio.models import SiteSetting
        from platform_studio.utils import invalidate
        for key, value in (('hero_video_light', '/media/hero/light.mp4'),
                           ('hero_video_dark', '/media/hero/dark.mp4')):
            SiteSetting.objects.update_or_create(
                key=key,
                defaults={'label': key, 'value': value, 'group': 'homepage'},
            )
        invalidate()
        try:
            response = self.client.get(reverse('shop:home'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'hero-video-aq--video')
            self.assertContains(response, 'data-hero-video-element')
            self.assertContains(response, '/media/hero/light.mp4')
            self.assertNotContains(response, 'hero-video-aq-stage')
        finally:
            SiteSetting.objects.filter(key__in=('hero_video_light', 'hero_video_dark')).delete()
            invalidate()

    def test_home_renders_default_video_hero_when_settings_empty(self):
        from platform_studio.models import SiteSetting
        from platform_studio.utils import invalidate
        SiteSetting.objects.update_or_create(
            key='hero_video_light',
            defaults={'label': 'hero_video_light', 'value': '', 'group': 'homepage'},
        )
        SiteSetting.objects.update_or_create(
            key='hero_video_dark',
            defaults={'label': 'hero_video_dark', 'value': '', 'group': 'homepage'},
        )
        invalidate()
        try:
            response = self.client.get(reverse('shop:home'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'hero-video-aq--video')
            self.assertContains(response, 'data-hero-video-element')
            self.assertContains(response, 'data-light="/static/hero/light_hero.mp4"')
            self.assertContains(response, 'data-dark="/static/hero/dark_hero.mp4"')
        finally:
            SiteSetting.objects.filter(key__in=('hero_video_light', 'hero_video_dark')).delete()
            invalidate()

class TestHomepageRoleSelection(TestCase):
    """The role picker that sits between the parallax hero and the features grid.

    Each card is a single link covering the whole surface, so the href itself
    has to carry the auth decision rather than leaving it to a view further
    down the funnel.
    """

    def setUp(self):
        self.url = reverse('shop:home')

    def card_href(self, role):
        html = self.client.get(self.url).content.decode()
        match = re.search(
            r'class="role-aq-card role-aq-card--%s[^"]*"\s*\n?\s*href="([^"]+)"' % role,
            html,
        )
        self.assertIsNotNone(match, 'no %s card link in the homepage' % role)
        return match.group(1)

    def test_section_sits_between_parallax_hero_and_features(self):
        html = self.client.get(self.url).content.decode()
        self.assertLess(html.index('parallax-aq-fade'), html.index('roles-aq-grid'))
        self.assertLess(html.index('roles-aq-grid'), html.index('features-aq-grid'))

    def test_surrounding_homepage_sections_are_untouched(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('parallax-aq-title', html)
        self.assertIn('Scroll slowly', html)
        self.assertIn('features-aq-grid', html)
        self.assertIn('collections-aq', html)

    def test_headline_and_both_cards_render(self):
        # Unescape so this asserts on what a visitor actually reads.
        html = unescape(self.client.get(self.url).content.decode())
        self.assertIn('How would you like to use', html)
        self.assertIn('take you to the right place', html)
        self.assertIn("I'm a Seller", html)
        self.assertIn("I'm a Customer", html)

    def test_seller_card_advertises_the_ai_pipeline(self):
        html = self.client.get(self.url).content.decode()
        for label in ('AI assisted', 'AI Image', 'Smart Catalog', 'Smart Price', 'Publish'):
            self.assertIn(label, html)

    def test_no_nested_links_inside_the_cards(self):
        # The whole card is the <a>; a nested one would be invalid markup and
        # would break the single-tab-stop keyboard order.
        html = self.client.get(self.url).content.decode()
        cards = re.findall(r'<a class="role-aq-card.*?</a>', html, re.S)
        self.assertEqual(len(cards), 2)
        for card in cards:
            self.assertEqual(card.count('<a'), 1, 'nested link inside a role card')

    def test_anonymous_seller_card_opens_the_existing_signup(self):
        self.assertEqual(self.card_href('seller'), reverse('accounts:become_seller'))

    def test_signed_in_non_seller_opens_the_existing_signup(self):
        user = get_user_model().objects.create_user(username='role-non-seller', password='pw')
        self.client.force_login(user)
        self.assertEqual(self.card_href('seller'), reverse('accounts:become_seller'))

    def test_seller_reaches_the_existing_dashboard(self):
        user = get_user_model().objects.create_user(username='role-seller', password='pw')
        SellerProfile.objects.create(user=user)
        self.client.force_login(user)
        self.assertEqual(self.card_href('seller'), reverse('seller:seller_dashboard'))

    def test_customer_card_opens_the_existing_shop_listing(self):
        self.assertEqual(self.card_href('customer'), reverse('shop:product_list'))

    def test_flow_rail_has_one_marker_per_stage(self):
        # A marker per stage is what makes the rail read as a sequence.
        html = self.client.get(self.url).content.decode()
        seller = re.search(r'role-aq-card--seller.*?role-aq-flow-dots(.*?)</div>', html, re.S)
        customer = re.search(r'role-aq-card--customer.*?role-aq-flow-dots(.*?)</div>', html, re.S)
        self.assertIsNotNone(seller)
        self.assertIsNotNone(customer)
        self.assertEqual(seller.group(1).count('role-aq-dot'), 6)
        self.assertEqual(customer.group(1).count('role-aq-dot'), 3)

    def test_scroll_choreography_is_wired_up(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('role-select.js', html)
        self.assertIn('role-select.css', html)
        self.assertIn('roles-aq-wash', html)

    def test_visibility_is_gated_on_javascript(self):
        # The aq-js class is what lets the stylesheet hide the start states at
        # all, so it has to be set before the section paints.
        html = self.client.get(self.url).content.decode()
        gate = html.index("classList.add('aq-js')")
        self.assertLess(gate, html.index('roles-aq-grid'))

    def test_motion_off_resolves_to_the_visible_state(self):
        # A CSS-only guarantee: with reduced motion the section must not be
        # left stranded behind the staged transition delays.
        path = finders.find('css/role-select.css')
        self.assertIsNotNone(path, 'role-select.css is not discoverable by staticfiles')
        with open(path, encoding='utf-8') as handle:
            css = handle.read()
        self.assertIn('.roles-aq.is-armed.roles-aq-motion-off', css)
        reduced = css[css.index('.roles-aq.is-armed.roles-aq-motion-off .roles-aq-intro > *'):]
        self.assertIn('opacity: 1;', reduced)
        self.assertIn('transition-delay: 0ms !important;', reduced)
