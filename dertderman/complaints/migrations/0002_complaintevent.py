from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def seed_existing_timelines(apps, schema_editor):
    Complaint = apps.get_model("complaints", "Complaint")
    ComplaintEvent = apps.get_model("complaints", "ComplaintEvent")
    status_types = {
        "PENDING": "PENDING",
        "PUBLISHED": "PUBLISHED",
        "RESOLVED": "RESOLVED",
        "REJECTED": "REJECTED",
    }
    events = []
    for complaint in Complaint.objects.all().iterator():
        events.append(ComplaintEvent(
            complaint_id=complaint.pk,
            event_type="CREATED",
            actor_type="SYSTEM",
            message="Şikayetiniz oluşturuldu ve güvenle kaydedildi.",
            source_key=f"complaint:{complaint.pk}:created",
            occurred_at=complaint.created_at,
        ))
        events.append(ComplaintEvent(
            complaint_id=complaint.pk,
            event_type=status_types[complaint.status],
            actor_type="SYSTEM",
            message="Mevcut şikayet durumu zaman çizelgesine aktarıldı.",
            source_key=f"complaint:{complaint.pk}:initial:{complaint.status}",
            occurred_at=complaint.updated_at,
        ))
    ComplaintEvent.objects.bulk_create(events, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("complaints", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ComplaintEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("CREATED", "Şikayet oluşturuldu"), ("PENDING", "İncelemeye alındı"), ("PUBLISHED", "Yayınlandı"), ("COMPANY_RESPONDED", "Şirket cevapladı"), ("RESOLVED", "Çözüldü"), ("REJECTED", "Reddedildi")], max_length=24)),
                ("actor_type", models.CharField(choices=[("SYSTEM", "Sistem"), ("USER", "Kullanıcı"), ("ADMIN", "Yönetici"), ("COMPANY", "Şirket")], default="SYSTEM", max_length=12)),
                ("message", models.CharField(max_length=300)),
                ("source_key", models.CharField(max_length=180, unique=True)),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("complaint", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="complaints.complaint")),
            ],
            options={"ordering": ("occurred_at", "pk")},
        ),
        migrations.AddIndex(
            model_name="complaintevent",
            index=models.Index(fields=["complaint", "occurred_at"], name="complaint_timeline"),
        ),
        migrations.RunPython(seed_existing_timelines, migrations.RunPython.noop),
    ]
