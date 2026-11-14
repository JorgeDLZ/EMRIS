from django.contrib import admin
from django.urls import include, path

from config.admin import ThrottledAdminAuthenticationForm, superuser_only
from config.views import health, home

admin.site.has_permission = superuser_only
admin.site.login_form = ThrottledAdminAuthenticationForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("accounts/", include("apps.accounts.urls")),
    path("places/", include("apps.places.urls")),
    path("emergencies/", include("apps.emergencies.urls")),
    path("plans/", include("apps.plans.urls")),
    path("intelligence/", include("apps.intelligence.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("history/", include("apps.history.urls")),
    path("", home, name="home"),
]
