from django.urls import path

from . import views

app_name = "emergencies"

urlpatterns = [
    path("types/", views.type_list, name="type_list"),
    path("types/new/", views.type_create, name="type_create"),
    path("types/<int:pk>/", views.type_edit, name="type_edit"),
]
