from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0009_companysubscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="rejected_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="rejection_reason",
            field=models.CharField(
                blank=True,
                default="",
                max_length=1000,
            ),
        ),
    ]
