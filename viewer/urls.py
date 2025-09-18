from django.urls import path
from . import views

urlpatterns = [
    path("drive/<str:route_id>/toggle_preserve/", views.toggle_preserve, name="toggle_preserve"),
    path("", views.drive_list, name="drive_list"),
    path("drive/<str:route_id>/", views.drive_detail, name="drive_detail"),
]
