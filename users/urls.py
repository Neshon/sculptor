from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("profile/", views.profile, name="profile"),
    path("password/", views.PasswordChange.as_view(), name="password"),
    path("roles/", views.roles, name="roles"),
    path("new/", views.create_user, name="create"),
    path("access/", views.access_log, name="access-log"),
]
