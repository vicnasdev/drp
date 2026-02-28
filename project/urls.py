from django.contrib import admin
from django.urls import path, include
from core import views

handler400 = 'core.views.error_handler.bad_request'
handler403 = 'core.views.error_handler.forbidden'
handler404 = 'core.views.error_handler.not_found'
handler500 = 'core.views.error_handler.server_error'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('core.api.urls')),
    path('', views.home, name='home'),        # add back
    path('billing/', include('billing.urls')),
    path('help/', include('help.urls')),
    path('', include('core.urls')),
]