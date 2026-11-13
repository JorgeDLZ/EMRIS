from django.urls import path

from apps.history import views

app_name = "history"

urlpatterns = [
    path("", views.record_list, name="record_list"),
    path("export.xlsx", views.export, name="export"),
    path("<int:source_row>/", views.record_detail, name="record_detail"),
]
