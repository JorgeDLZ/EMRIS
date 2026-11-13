from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("risk/", views.ranking, name="ranking"),
    path("emergencies.csv", views.export_emergencies, name="export_emergencies"),
    path("risk.csv", views.export_ranking, name="export_ranking"),
]
