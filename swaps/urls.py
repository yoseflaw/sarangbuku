from django.urls import path

from . import views

app_name = "swaps"

urlpatterns = [
    path("lini/", views.lini, name="lini"),
    path("minat/ajukan/<int:requested_copy_id>/", views.minat_create, name="minat_create"),
    path("minat/<int:pk>/", views.minat_detail, name="minat_detail"),
    path("minat/<int:pk>/batal/", views.minat_withdraw, name="minat_withdraw"),
    path("minat/<int:pk>/tolak/", views.minat_reject, name="minat_reject"),
    path("minat/<int:pk>/terima/", views.minat_accept, name="minat_accept"),
]
