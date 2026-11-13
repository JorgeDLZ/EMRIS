from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("risk/", views.ranking, name="ranking"),
    path("emergencies.xlsx", views.export_emergencies, name="export_emergencies"),
    path("risk.xlsx", views.export_ranking, name="export_ranking"),
]
