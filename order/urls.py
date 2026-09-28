from django.urls import path
from . import views

app_name = 'order'

# Order pages are keyed by the public reference (SEED-2026-000149), never by the
# primary key, so a link the customer saves or shares reads like a receipt.
# Literal routes come first so they can't be shadowed by <orderref:...>.
urlpatterns = [
    path('create/', views.order_create, name='order_create'),
    path('locate/', views.autofill_address, name='autofill_address'),
    path('my-orders/', views.my_orders, name='my_orders'),

    path('<orderref:order_ref>/', views.order_detail, name='order_detail'),
    path('<orderref:order_ref>/cancel/', views.order_cancel, name='order_cancel'),
    path('<orderref:order_ref>/return/', views.request_return, name='request_return'),
    path('<orderref:order_ref>/invoice/', views.order_invoice_pdf, name='order_invoice'),

    # Legacy numeric URLs (/order/orders/149/) — order confirmation emails,
    # bookmarks and in-flight payment links still use the raw id. They resolve to
    # the same views, which permanently redirect to the reference form on GET.
    path('orders/<int:order_ref>/', views.order_detail, name='order_detail_legacy'),
    path('orders/<int:order_ref>/cancel/', views.order_cancel, name='order_cancel_legacy'),
    path('orders/<int:order_ref>/return/', views.request_return, name='request_return_legacy'),
    path('orders/<int:order_ref>/invoice/', views.order_invoice_pdf, name='order_invoice_legacy'),
]
