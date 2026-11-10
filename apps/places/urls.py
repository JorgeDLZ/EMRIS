from django.urls import path

from . import views

app_name = "places"

urlpatterns = [
    path("", views.municipality_list, name="municipality_list"),
    path("new/", views.municipality_create, name="municipality_create"),
    path("pending/", views.municipality_pending, name="municipality_pending"),
    path("<int:pk>/approve/", views.municipality_approve, name="municipality_approve"),
    path("<int:pk>/reject/", views.municipality_reject, name="municipality_reject"),
]
