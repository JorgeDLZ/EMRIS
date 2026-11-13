from django.urls import path

from apps.intelligence import views

app_name = "intelligence"

urlpatterns = [
    path("", views.model_list, name="model_list"),
    path("retrain/", views.retrain, name="retrain"),
    path("versions/<int:pk>/activate/", views.activate, name="activate"),
]
