from django.urls import path

from drive import views

urlpatterns = [
    path("explore/", views.explore, name="explore"),
    path("embed/<str:key>/", views.embed, name="embed"),
    path("@<str:username>/", views.profile, name="profile"),
    path("@<str:username>/<path:path>/", views.path_view, name="path_view"),
    # Key routes — order matters: /raw/ and /download/ before catch-all
    path("<str:key>/raw/", views.key_raw, name="key_raw"),
    path("<str:key>/download/", views.key_download, name="key_download"),
    path("<str:key>/decrypt/", views.key_decrypt, name="key_decrypt"),
    path("<str:key>/", views.key_view, name="key_view"),
]
