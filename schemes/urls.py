from django.urls import path

from . import views

app_name = 'schemes'

urlpatterns = [
    path('', views.schemes_list, name='schemes_list'),
]