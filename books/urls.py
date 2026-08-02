from django.urls import path

from . import views

app_name = "books"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("tambah/", views.add, name="add"),
    path("tambah/open-library/", views.open_library_search, name="open_library"),
    path("tambah/manual/", views.manual_create, name="manual_create"),
    path("tambah/<int:book_id>/", views.copy_create, name="copy_create"),
    path("salinan/<int:pk>/ubah/", views.copy_edit, name="copy_edit"),
    path("salinan/<int:pk>/hapus/", views.copy_delete, name="copy_delete"),
]