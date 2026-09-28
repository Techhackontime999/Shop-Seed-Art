"""Order URLs are addressed by the public reference (SEED-2026-000149), never the
raw primary key — with the old numeric URLs kept alive as a redirect so links
already in the wild (order confirmation emails, bookmarks, in-flight payment
links) keep working.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import resolve, reverse

from order.access import get_order_by_ref
from order.models import Order, OrderItem
from order.views import order_cancel, order_detail, order_invoice_pdf, request_return
from payments.views import checkout, payment_error, payment_success
from seller.views import update_order_status
from shop.models import Category, Product
from shipping.views import order_tracking, shipping_select

REF = 'SEED-2026-0000042'


class OrderUrlShapeTests(TestCase):
    """The canonical URL for an order reads like a receipt, not a database row."""

    def test_canonical_urls_use_the_order_reference(self):
        ref = REF
        self.assertEqual(
            reverse('order:order_detail', args=[ref]), f'/order/{ref}/',
        )
        self.assertEqual(
            reverse('order:order_invoice', args=[ref]), f'/order/{ref}/invoice/',
        )
        self.assertEqual(
            reverse('order:order_cancel', args=[ref]), f'/order/{ref}/cancel/',
        )
        self.assertEqual(
            reverse('order:request_return', args=[ref]), f'/order/{ref}/return/',
        )
        self.assertEqual(
            reverse('payments:checkout', args=[ref]), f'/payments/checkout/{ref}/',
        )
        self.assertEqual(
            reverse('payments:success', args=[ref]), f'/payments/success/{ref}/',
        )
        self.assertEqual(
            reverse('payments:error', args=[ref]), f'/payments/error/{ref}/',
        )
        self.assertEqual(
            reverse('payments:verify', args=[ref]), f'/payments/verify/{ref}/',
        )
        self.assertEqual(
            reverse('shipping:shipping_select', args=[ref]), f'/shipping/select/{ref}/',
        )
        self.assertEqual(
            reverse('shipping:order_tracking', args=[ref]), f'/shipping/tracking/{ref}/',
        )
        self.assertEqual(
            reverse('seller:update_order_status', args=[ref]),
            f'/seller/orders/update/{ref}/',
        )

    def test_canonical_url_carries_no_raw_primary_key(self):
        self.assertEqual(reverse('order:order_detail', args=[REF]), '/order/SEED-2026-0000042/')

    def test_canonical_urls_resolve_to_their_views(self):
        for name, view in (
            ('order:order_detail', order_detail),
            ('order:order_invoice', order_invoice_pdf),
            ('order:order_cancel', order_cancel),
            ('order:request_return', request_return),
            ('payments:checkout', checkout),
            ('payments:success', payment_success),
            ('payments:error', payment_error),
            ('shipping:shipping_select', shipping_select),
            ('shipping:order_tracking', order_tracking),
        ):
            self.assertEqual(resolve(reverse(name, args=[REF])).func, view, name)

    def test_literal_order_routes_are_not_shadowed_by_the_reference_pattern(self):
        for name in ('order:order_create', 'order:autofill_address', 'order:my_orders'):
            url = reverse(name)
            self.assertNotIn(REF, url)
            self.assertEqual(resolve(url).url_name, name.split(':')[1])


class OrderRefResolutionTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            first_name='Ada', last_name='Lovelace', email='ada@example.com',
            address='5 Analytical Way', postal_code='560001', city='Bangalore',
        )

    def test_url_ref_is_the_order_number(self):
        self.assertEqual(self.order.url_ref, self.order.order_number)
        self.assertTrue(self.order.url_ref.startswith('SEED-'))

    def test_reference_resolves(self):
        self.assertEqual(get_order_by_ref(self.order.order_number), self.order)

    def test_legacy_numeric_id_resolves(self):
        self.assertEqual(get_order_by_ref(str(self.order.pk)), self.order)

    def test_unknown_reference_resolves_to_nothing(self):
        self.assertIsNone(get_order_by_ref('SEED-2026-999999'))
        self.assertIsNone(get_order_by_ref(str(self.order.pk) + '999'))
        self.assertIsNone(get_order_by_ref('not-a-ref'))
        self.assertIsNone(get_order_by_ref(''))


class LegacyOrderUrlTests(TestCase):
    """The old numeric URLs must keep working — permanently redirected on GET and
    handled in place on POST (a 301 would silently turn a POST into a GET)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='buyer', password='pass1234')
        self.category = Category.objects.create(name='Audio', slug='audio')
        self.product = Product.objects.create(
            category=self.category, name='Nimbus Headphones', slug='nimbus-headphones',
            price=Decimal('100.00'), stock=10,
        )
        self.order = Order.objects.create(
            user=self.user, first_name='Ada', last_name='Lovelace', email='ada@example.com',
            address='5 Analytical Way', postal_code='560001', city='Bangalore',
            phone='9999999999', state='Karnataka', country='India',
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, price=Decimal('100.00'), quantity=2,
        )
        self.client = Client(SERVER_NAME='localhost')
        self.client.force_login(self.user)
        self.legacy = f'/order/orders/{self.order.pk}/'

    def test_legacy_detail_permanently_redirects_to_the_reference(self):
        response = self.client.get(self.legacy)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response['Location'], reverse('order:order_detail', args=[self.order.url_ref]),
        )

    def test_legacy_redirect_lands_on_the_order(self):
        response = self.client.get(self.legacy, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nimbus Headphones')

    def test_legacy_invoice_and_tracking_redirect(self):
        for legacy_name, canonical_name in (
            ('order:order_invoice_legacy', 'order:order_invoice'),
            ('shipping:order_tracking_legacy', 'shipping:order_tracking'),
        ):
            response = self.client.get(reverse(legacy_name, args=[self.order.pk]))
            self.assertEqual(response.status_code, 301, legacy_name)
            self.assertEqual(
                response['Location'],
                reverse(canonical_name, args=[self.order.url_ref]),
            )

    def test_legacy_checkout_and_payment_pages_redirect(self):
        for legacy_name, canonical_name in (
            ('payments:checkout_legacy', 'payments:checkout'),
            ('payments:error_legacy', 'payments:error'),
        ):
            response = self.client.get(reverse(legacy_name, args=[self.order.pk]))
            self.assertEqual(response.status_code, 301, legacy_name)
            self.assertEqual(
                response['Location'],
                reverse(canonical_name, args=[self.order.url_ref]),
            )

    def test_legacy_success_page_redirects_once_the_order_is_paid(self):
        self.order.paid = True
        self.order.save(update_fields=['paid'])
        response = self.client.get(reverse('payments:success_legacy', args=[self.order.pk]))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response['Location'],
            reverse('payments:success', args=[self.order.url_ref]),
        )

    def test_legacy_post_still_cancels_the_order(self):
        # A 301 here would turn the POST into a GET and silently do nothing.
        response = self.client.post(
            reverse('order:order_cancel_legacy', args=[self.order.pk]), {'reason': 'changed mind'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'], reverse('order:order_detail', args=[self.order.url_ref]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)

    def test_legacy_urls_do_not_bypass_access_control(self):
        self.client.force_login(get_user_model().objects.create_user(
            username='stranger', password='pass1234',
        ))
        response = self.client.get(self.legacy)
        self.assertEqual(response.status_code, 404)
