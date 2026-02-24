from django.urls import path
from . import views
from .licensing import licensing_page, licensing_generate

urlpatterns = [
    path('checkout/<str:plan>/', views.checkout, name='billing_checkout'),
    path('portal/', views.portal, name='billing_portal'),
    path('webhook/', views.webhook, name='billing_webhook'),
    path('licensing/', licensing_page, name='licensing'),
    path('licensing/generate/', licensing_generate, name='licensing_generate'),
]