from django.urls import path
from . import views

app_name = 'payments'

# Every order-scoped payment page is keyed by the public order reference
# (SEED-2026-000149). The *_legacy patterns keep the old numeric URLs working for
# payment links already created on Razorpay and for links in the wild; the views
# permanently redirect them to the reference form on GET.
urlpatterns = [
    path('callback/', views.payment_callback, name='callback'),
    path('link-callback/', views.payment_link_callback, name='link_callback'),
    path('webhook/', views.payment_webhook, name='webhook'),

    path('checkout/<orderref:order_ref>/', views.checkout, name='checkout'),
    path('verify/<orderref:order_ref>/', views.payment_verify, name='verify'),
    path('success/<orderref:order_ref>/', views.payment_success, name='success'),
    path('error/<orderref:order_ref>/', views.payment_error, name='error'),

    path('checkout/<int:order_ref>/', views.checkout, name='checkout_legacy'),
    path('verify/<int:order_ref>/', views.payment_verify, name='verify_legacy'),
    path('success/<int:order_ref>/', views.payment_success, name='success_legacy'),
    path('error/<int:order_ref>/', views.payment_error, name='error_legacy'),
]
