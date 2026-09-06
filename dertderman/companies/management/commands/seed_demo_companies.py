from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from companies.models import Company


DEMO_COMPANY_NAMES = (
    "Demo Teknoloji",
    "Demo Market",
    "Demo Kargo",
    "Demo Telekom",
    "Demo Banka",
)


class Command(BaseCommand):
    help = "Yalnızca DEBUG=True ortamında development/test için demo şirketler ekler."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo_companies yalnızca DEBUG=True ortamında çalışabilir.")

        created_count = 0
        with transaction.atomic():
            for name in DEMO_COMPANY_NAMES:
                company, created = Company.objects.get_or_create(
                    name=name,
                    defaults={
                        "is_active": True,
                        "description": "Yalnızca development/test amacıyla oluşturulmuş demo şirket kaydıdır. Gerçek bir şirketi temsil etmez.",
                    },
                )
                if not company.is_active:
                    company.is_active = True
                    company.save(update_fields=["is_active", "updated_at"])
                created_count += int(created)
                self.stdout.write(f"{name}: {'oluşturuldu' if created else 'mevcut kayıt kullanıldı'}")

        self.stdout.write(self.style.SUCCESS(
            f"Development/test: {created_count} yeni demo şirket, {len(DEMO_COMPANY_NAMES)} aktif demo şirket."
        ))
