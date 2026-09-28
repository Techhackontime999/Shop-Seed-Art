from django.urls import path
from . import views

app_name = 'shipping'

urlpatterns = [
    path('addresses/', views.address_list, name='address_list'),
    path('addresses/create/', views.address_create, name='address_create'),
    path('addresses/<int:address_id>/update/', views.address_update, name='address_update'),
    path('addresses/<int:address_id>/delete/', views.address_delete, name='address_delete'),
    path('select/<orderref:order_ref>/', views.shipping_select, name='shipping_select'),
    path('tracking/<orderref:order_ref>/', views.order_tracking, name='order_tracking'),
    # Legacy numeric order URLs — still linked from confirmation emails in the
    # wild; the views permanently redirect them to the reference form on GET.
    path('select/<int:order_ref>/', views.shipping_select, name='shipping_select_legacy'),
    path('tracking/<int:order_ref>/', views.order_tracking, name='order_tracking_legacy'),
]
