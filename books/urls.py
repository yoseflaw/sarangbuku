from django.urls import path

from . import views

app_name = "books"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("salinan/<int:pk>/ubah/", views.copy_edit, name="copy_edit"),
    path("salinan/<int:pk>/hapus/", views.copy_delete, name="copy_delete"),
]