from django.db import migrations, models


def forwards(apps, schema_editor):
    BookCopy = apps.get_model("books", "BookCopy")
    BookCopy.objects.filter(is_available=True).update(availability_status="available")
    BookCopy.objects.filter(is_available=False).update(availability_status="unavailable")


def backwards(apps, schema_editor):
    BookCopy = apps.get_model("books", "BookCopy")
    BookCopy.objects.filter(availability_status="available").update(is_available=True)
    BookCopy.objects.exclude(availability_status="available").update(is_available=False)


class Migration(migrations.Migration):
    dependencies = [("books", "0002_wishlistitem")]

    operations = [
        migrations.AddField(
            model_name="bookcopy",
            name="availability_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("available", "Tersedia"),
                    ("reserved", "Ada Peminat"),
                    ("unavailable", "Tidak tersedia"),
                ],
                max_length=11,
                null=True,
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="bookcopy", name="is_available"),
        migrations.AlterField(
            model_name="bookcopy",
            name="availability_status",
            field=models.CharField(
                choices=[
                    ("available", "Tersedia"),
                    ("reserved", "Ada Peminat"),
                    ("unavailable", "Tidak tersedia"),
                ],
                default="available",
                max_length=11,
            ),
        ),
        migrations.AddConstraint(
            model_name="bookcopy",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    availability_status__in=["available", "reserved", "unavailable"]
                ),
                name="books_bookcopy_availability_valid",
            ),
        ),
    ]
