from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class BookCopyAvailabilityMigrationTests(TransactionTestCase):
    migrate_from = ("books", "0002_wishlistitem")
    migrate_to = ("books", "0003_bookcopy_availability_status")

    def tearDown(self):
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def test_forward_and_reverse_values_are_preserved(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        User = old_apps.get_model("accounts", "User")
        Book = old_apps.get_model("books", "Book")
        BookCopy = old_apps.get_model("books", "BookCopy")
        owner = User.objects.create(email="migration@example.com", display_name="Migrasi")
        book = Book.objects.create(title="Migrasi", authors="Penulis", language="Indonesia")
        available = BookCopy.objects.create(
            owner=owner, book=book, condition="good", is_available=True
        )
        unavailable = BookCopy.objects.create(
            owner=owner, book=book, condition="fair", is_available=False
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        new_apps = executor.loader.project_state([self.migrate_to]).apps
        MigratedCopy = new_apps.get_model("books", "BookCopy")
        self.assertEqual(
            MigratedCopy.objects.get(pk=available.pk).availability_status,
            "available",
        )
        self.assertEqual(
            MigratedCopy.objects.get(pk=unavailable.pk).availability_status,
            "unavailable",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        restored_apps = executor.loader.project_state([self.migrate_from]).apps
        RestoredCopy = restored_apps.get_model("books", "BookCopy")
        self.assertTrue(RestoredCopy.objects.get(pk=available.pk).is_available)
        self.assertFalse(RestoredCopy.objects.get(pk=unavailable.pk).is_available)
