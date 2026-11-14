from django.contrib.auth import views as auth_views
from django.urls import path

from apps.accounts import views
from apps.accounts.forms import ThrottledAuthenticationForm

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=ThrottledAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("pending/", views.pending, name="pending"),
    path("users/", views.user_list, name="user_list"),
    path("users/<int:pk>/role/", views.user_role, name="user_role"),
]
