from django.urls import path

from . import views

app_name = "swaps"

urlpatterns = [
    path("minat/ajukan/<int:requested_copy_id>/", views.minat_create, name="minat_create"),
    path("minat/<int:pk>/", views.minat_detail, name="minat_detail"),
]
