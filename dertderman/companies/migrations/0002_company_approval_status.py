from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="approval_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Onay bekliyor"),
                    ("APPROVED", "Onaylandı"),
                    ("REJECTED", "Reddedildi"),
                ],
                db_index=True,
                default="APPROVED",
                max_length=20,
            ),
        ),
    ]
