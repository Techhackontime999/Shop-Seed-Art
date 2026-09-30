"""Publish endpoint tests: AI Studio -> real Product.

These are the guard-rails for the flow that actually writes to the shop:
ownership, verification, slug uniqueness, image handling, and the promise
that publishing never silently flips a product live.
"""

import json
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image

from accounts.models import SellerProfile
from shop.models import Category, Product, ProductImage, SubCategory

from .models import EnhancementStatus, ImageEnhancementJob, Selection


def png_bytes(size=(200, 200), color=(200, 60, 60)):
    import io
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


def jpeg_bytes(size=(200, 200), color=(60, 120, 200)):
    import io
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='JPEG')
    return buf.getvalue()


class PublishTestBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('studio_seller', 'studio@example.com', 'pw')
        self.profile = SellerProfile.objects.create(
            user=self.user, shop_name='Studio Shop', bank_account='123456789',
            account_holder_name='Seller', ifsc_code='HDFC0001234',
            phone='9999999999', address='Test address',
            is_email_verified=True, is_phone_verified=True,
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.url = '/ai/publish/'
        # Publishing resolves the category against the shop's own taxonomy and
        # refuses a name that is not a row, so the department has to exist.
        # Created here rather than relying on the development database.
        self.category = Category.objects.create(name='Home Textiles')
        self.subcategory = SubCategory.objects.create(
            name='Bedsheets', category=self.category)
        self._media = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media)
        self._override.enable()

    def tearDown(self):
        self._override.disable()

    def payload(self, **overrides):
        data = {
            'title': 'Handwoven Cotton Table Runner',
            'description': 'A handwoven cotton runner with a soft fringe.',
            'category': 'Home Textiles',
            'price': '499.00',
            'stock': 5,
        }
        data.update(overrides)
        return data

    def post(self, data):
        return self.client.post(self.url, json.dumps(data), content_type='application/json')

    def make_job(self, seller=None, **kwargs):
        defaults = {
            'seller': seller or self.user,
            'status': EnhancementStatus.COMPLETED,
            'original': SimpleUploadedFile('orig.jpg', jpeg_bytes()),
            'enhanced': SimpleUploadedFile('enh.jpg', jpeg_bytes(color=(90, 90, 90))),
        }
        defaults.update(kwargs)
        return ImageEnhancementJob.objects.create(**defaults)


class TestPublishHappyPath(PublishTestBase):
    def test_creates_a_product_owned_by_the_seller_profile(self):
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 201, response.content[:300])

        product = Product.objects.get()
        self.assertEqual(product.name, 'Handwoven Cotton Table Runner')
        self.assertEqual(product.seller, self.profile)
        self.assertEqual(product.price, Decimal('499.00'))
        self.assertEqual(product.stock, 5)
        self.assertEqual(product.category.name, 'Home Textiles')
        self.assertEqual(product.slug, 'handwoven-cotton-table-runner')
        self.assertIn(product.get_absolute_url(), response.json()['product_url'])

    def test_a_valid_payload_never_returns_a_server_error(self):
        """A 500 here means the seller simply cannot publish.

        The taxonomy helpers are imported inside the view to keep shop.models
        out of the import graph, and a function-local import anywhere in the
        body shadows the name for the whole function. That mistake returned
        UnboundLocalError - a 500 - for every single publish, while the
        endpoint's own error handling still looked perfectly healthy.
        """
        response = self.post(self.payload())
        self.assertLess(response.status_code, 500, response.content[:300])

    def test_the_subcategory_is_resolved_from_the_chosen_category(self):
        response = self.post(self.payload(subcategory='Bedsheets'))
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Product.objects.get().subcategory, self.subcategory)

    def test_a_subcategory_from_another_department_is_refused(self):
        response = self.post(self.payload(subcategory='Canvas & Prints'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'unknown_subcategory')
        self.assertFalse(Product.objects.exists())

    def test_product_is_not_live_until_reviewed(self):
        """Publishing a draft must never put an unreviewed product on sale."""
        self.post(self.payload())
        self.assertFalse(Product.objects.get().available)

    def test_reuses_an_existing_category(self):
        """Publishing must never invent a department.

        A seller's phrasing becoming a new category row is how a shop slowly
        ends up with "Home Textiles" three times over, so the existing row is
        resolved and reused instead.
        """
        before = Category.objects.count()
        self.post(self.payload())
        self.assertEqual(Category.objects.count(), before)
        self.assertEqual(Product.objects.get().category, self.category)

    def test_repeated_titles_get_distinct_slugs(self):
        self.post(self.payload())
        self.post(self.payload())
        self.assertEqual(Product.objects.count(), 2)
        slugs = set(Product.objects.values_list('slug', flat=True))
        self.assertEqual(len(slugs), 2)

    def test_accepts_name_as_an_alias_for_title(self):
        payload = self.payload()
        payload.pop('title')
        payload['name'] = 'Blue Ceramic Vase'
        self.assertEqual(self.post(payload).status_code, 201)
        self.assertEqual(Product.objects.get().name, 'Blue Ceramic Vase')

    def test_long_title_is_truncated_not_rejected(self):
        self.post(self.payload(title='x' * 400))
        self.assertEqual(Product.objects.get().name, 'x' * 200)

    def test_works_without_a_stock_value(self):
        payload = self.payload()
        payload.pop('stock')
        self.assertEqual(self.post(payload).status_code, 201)
        self.assertEqual(Product.objects.get().stock, 0)


class TestPublishImageHandling(PublishTestBase):
    def test_attaches_the_enhanced_image_by_default(self):
        job = self.make_job()
        response = self.post(self.payload(enhancement_job=str(job.id)))
        self.assertEqual(response.status_code, 201, response.content[:300])

        product = Product.objects.get()
        self.assertTrue(product.image.name)
        self.assertIn('enh', product.image.name)
        self.assertTrue(ProductImage.objects.filter(product=product, is_main=True).exists())

    def test_keeps_the_original_when_the_seller_chose_it(self):
        job = self.make_job(selection=Selection.ORIGINAL)
        self.post(self.payload(enhancement_job=str(job.id)))
        self.assertIn('orig', Product.objects.get().image.name)

    def test_explicit_use_enhanced_false_keeps_the_original(self):
        job = self.make_job()
        self.post(self.payload(enhancement_job=str(job.id), use_enhanced=False))
        self.assertIn('orig', Product.objects.get().image.name)

    def test_image_is_copied_so_draft_cleanup_cannot_orphan_it(self):
        job = self.make_job()
        self.post(self.payload(enhancement_job=str(job.id)))
        product = Product.objects.get()
        self.assertNotEqual(product.image.name, job.enhanced.name)
        self.assertTrue(product.image.storage.exists(product.image.name))

    def test_cannot_publish_someone_elses_draft(self):
        other = get_user_model().objects.create_user('other', 'o@example.com', 'pw')
        other_profile = SellerProfile.objects.create(
            user=other, shop_name='Other', bank_account='1',
            account_holder_name='O', ifsc_code='HDFC0001234',
            phone='9999999998', address='Elsewhere',
            is_email_verified=True, is_phone_verified=True)
        victim_job = self.make_job(seller=other)

        response = self.post(self.payload(enhancement_job=str(victim_job.id)))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(other_profile.products.count(), 0)

    def test_rejects_an_unfinished_job(self):
        job = self.make_job(status=EnhancementStatus.PROCESSING)
        response = self.post(self.payload(enhancement_job=str(job.id)))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Product.objects.count(), 0)

    def test_rejects_a_malformed_job_id(self):
        """A malformed id is a client error, not a lookup miss."""
        response = self.post(self.payload(enhancement_job='not-a-uuid'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'bad_job')
        self.assertEqual(Product.objects.count(), 0)

    def test_publishes_without_an_image_when_no_job_is_given(self):
        self.assertEqual(self.post(self.payload()).status_code, 201)
        self.assertFalse(Product.objects.get().image)


class TestPublishValidation(PublishTestBase):
    def test_requires_login(self):
        self.assertEqual(Client().post(
            self.url, json.dumps(self.payload()),
            content_type='application/json').status_code, 302)

    def test_requires_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            self.url, json.dumps(self.payload()), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Product.objects.count(), 0)

    def test_rejects_bad_json(self):
        response = self.client.post(self.url, 'not json', content_type='application/json')
        self.assertEqual(response.json()['error']['code'], 'bad_json')

    def test_rejects_a_json_array_body(self):
        response = self.client.post(self.url, '[]', content_type='application/json')
        self.assertEqual(response.json()['error']['code'], 'bad_json')

    def test_requires_a_title(self):
        response = self.post(self.payload(title='   '))
        self.assertEqual(response.json()['error']['code'], 'missing_title')

    def test_requires_a_description(self):
        self.assertEqual(
            self.post(self.payload(description='')).json()['error']['code'],
            'missing_description')

    def test_requires_a_category(self):
        self.assertEqual(
            self.post(self.payload(category='')).json()['error']['code'],
            'missing_category')

    def test_rejects_a_missing_price(self):
        self.assertEqual(self.post(self.payload(price=None)).json()['error']['code'], 'bad_price')

    def test_rejects_a_non_numeric_price(self):
        self.assertEqual(self.post(self.payload(price='free')).json()['error']['code'], 'bad_price')

    def test_rejects_a_zero_or_negative_price(self):
        self.assertEqual(self.post(self.payload(price='0')).json()['error']['code'], 'bad_price')
        self.assertEqual(self.post(self.payload(price='-5')).json()['error']['code'], 'bad_price')
        self.assertEqual(Product.objects.count(), 0)

    def test_rounds_a_long_decimal_price(self):
        self.post(self.payload(price='12.3456'))
        self.assertEqual(Product.objects.get().price, Decimal('12.35'))

    def test_rejects_a_negative_stock(self):
        self.post(self.payload(stock=-3))
        self.assertEqual(Product.objects.get().stock, 0)

    def test_rejects_a_non_numeric_stock_without_failing(self):
        response = self.post(self.payload(stock='many'))
        self.assertEqual(response.json()['error']['code'], 'bad_stock')
        self.assertEqual(Product.objects.count(), 0)

    def test_rejects_html_in_the_description(self):
        """The wizard feeds AI output in; it must not become stored XSS.

        bleach(strip=True) removes the tag but keeps its text, so the
        payload survives as inert text. What must not survive is the
        executable element itself.
        """
        self.post(self.payload(
            description='<script>alert(1)</script>Lovely cotton runner'))
        stored = Product.objects.get().description
        self.assertNotIn('<script', stored)
        self.assertNotIn('</script', stored)
        # The harmless text survives.
        self.assertIn('Lovely cotton runner', stored)

    def test_strips_event_handlers_and_javascript_urls(self):
        self.post(self.payload(
            description='<a href="javascript:alert(1)" onerror="steal()">Buy</a>'))
        stored = Product.objects.get().description
        self.assertNotIn('javascript:', stored)
        self.assertNotIn('onerror', stored)

    def test_a_description_of_only_a_script_is_rejected(self):
        response = self.post(self.payload(description='<script></script>'))
        self.assertEqual(response.json()['error']['code'], 'missing_description')
        self.assertEqual(Product.objects.count(), 0)

    def test_a_user_without_a_seller_profile_is_refused(self):
        orphan = get_user_model().objects.create_user('orphan', 'or@example.com', 'pw')
        c = Client()
        c.force_login(orphan)
        response = c.post(self.url, json.dumps(self.payload()),
                          content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'no_seller_profile')
        self.assertEqual(Product.objects.count(), 0)


class TestPublishIsRateLimited(PublishTestBase):
    def test_is_rate_limited(self):
        from django.core.cache import cache
        from django.test import override_settings as _ov
        cache.clear()
        with _ov(AI_TEXT_RATE_LIMIT=2):
            for _ in range(2):
                self.assertEqual(self.post(self.payload()).status_code, 201)
            limited = self.post(self.payload())
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()['error']['code'], 'rate_limited')
        self.assertEqual(Product.objects.count(), 2)
        cache.clear()


class TestPublishDoesNotTouchTheDraft(PublishTestBase):
    def test_publishing_does_not_change_the_job_status(self):
        job = self.make_job()
        self.post(self.payload(enhancement_job=str(job.id)))
        job.refresh_from_db()
        self.assertEqual(job.status, EnhancementStatus.COMPLETED)

    def test_publishing_leaves_the_selection_for_reuse(self):
        job = self.make_job(selection=Selection.ENHANCED)
        self.post(self.payload(enhancement_job=str(job.id)))
        job.refresh_from_db()
        self.assertEqual(job.selection, Selection.ENHANCED)

    def test_one_draft_can_be_published_twice(self):
        job = self.make_job()
        self.assertEqual(self.post(self.payload(enhancement_job=str(job.id))).status_code, 201)
        self.assertEqual(self.post(self.payload(enhancement_job=str(job.id))).status_code, 201)
        self.assertEqual(Product.objects.count(), 2)
