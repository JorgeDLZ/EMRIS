from django.contrib import admin
from django.urls import include, path

from config.views import health, home

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("accounts/", include("apps.accounts.urls")),
    path("places/", include("apps.places.urls")),
    path("emergencies/", include("apps.emergencies.urls")),
    path("plans/", include("apps.plans.urls")),
    path("", home, name="home"),
]
