from django.urls import path

from . import views

app_name = "emergencies"

urlpatterns = [
    path("", views.emergency_list, name="emergency_list"),
    path("new/", views.emergency_create, name="emergency_create"),
    path("types/", views.type_list, name="type_list"),
    path("types/new/", views.type_create, name="type_create"),
    path("types/<int:pk>/", views.type_edit, name="type_edit"),
    path("<int:pk>/", views.emergency_detail, name="emergency_detail"),
    path("<int:pk>/edit/", views.emergency_edit, name="emergency_edit"),
    path("<int:pk>/impact/", views.impact_edit, name="impact_edit"),
    path("<int:pk>/status/", views.status_change, name="status_change"),
    path("<int:pk>/notes/", views.note_add, name="note_add"),
    path("<int:pk>/seismic/confirm/", views.seismic_confirm, name="seismic_confirm"),
    path("<int:pk>/seismic/clear/", views.seismic_clear, name="seismic_clear"),
]
