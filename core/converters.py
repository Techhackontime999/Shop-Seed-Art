"""URL path converters shared across apps.

``orderref`` is the public identifier for an order in a URL. Order pages are
addressed by the human reference the customer already sees (``SEED-2026-000149``)
instead of the raw primary key, so a link in an email or a browser bookmark reads
like a receipt rather than a database row.

The legacy numeric form (``/order/149/``) is still accepted — order confirmation
emails, in-flight payment links and older bookmarks are in the wild — and is
permanently redirected to the reference form. Keep ``regex`` in sync with
``order.models._generate_order_number``.
"""

from django.urls import register_converter


class OrderRefConverter:
    """Matches either a public order reference or a legacy numeric order id."""

    regex = r'SEED-\d{4}-\d+|\d+'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return str(value)


register_converter(OrderRefConverter, 'orderref')
