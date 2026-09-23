from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("profile/", views.profile, name="profile"),
    path("roles/", views.roles, name="roles"),
    path("access/", views.access_log, name="access-log"),
]
