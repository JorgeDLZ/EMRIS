from django.contrib import admin
from django.urls import include, path

from config.views import health, home

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("accounts/", include("apps.accounts.urls")),
    path("places/", include("apps.places.urls")),
    path("", home, name="home"),
]
