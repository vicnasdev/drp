from django.urls import path
from . import views

urlpatterns = [
    path('',         views.index,    name='help_index'),
    path('cli/',     views.cli,      name='help_cli'),
    path('expiry/',  views.expiry,   name='help_expiry'),
    path('plans/',   views.plans,    name='help_plans'),
    path('security/', views.security, name='help_security'),
    path('ask/',     views.ask,      name='help_ask'),
]