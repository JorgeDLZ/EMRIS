from django.urls import path

from . import views

app_name = "plans"

urlpatterns = [
    path("resources/", views.resource_list, name="resource_list"),
    path("resources/new/", views.resource_create, name="resource_create"),
    path("resources/<int:pk>/", views.resource_edit, name="resource_edit"),
    path("actions/<int:pk>/edit/", views.action_edit, name="action_edit"),
    path("actions/<int:pk>/advance/", views.action_advance, name="action_advance"),
    path("assignments/<int:pk>/remove/", views.assignment_remove, name="assignment_remove"),
    path("<int:emergency_pk>/", views.plan_detail, name="plan_detail"),
    path("<int:emergency_pk>/start/", views.plan_start, name="plan_start"),
    path("<int:emergency_pk>/suggest/", views.plan_suggest, name="plan_suggest"),
    path("<int:emergency_pk>/suggest/add/", views.suggested_action_add, name="suggested_action_add"),
    path("<int:emergency_pk>/approve/", views.plan_approve, name="plan_approve"),
    path("<int:emergency_pk>/actions/new/", views.action_create, name="action_create"),
    path("<int:emergency_pk>/resources/", views.assignment_create, name="assignment_create"),
]
