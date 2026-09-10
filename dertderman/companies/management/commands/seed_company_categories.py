from django.core.management.base import BaseCommand

from companies.category_seed import seed_company_categories
from companies.models import CompanyCategory


class Command(BaseCommand):
    help = "DertDerman şirket kategorilerini idempotent olarak oluşturur."

    def handle(self, *args, **options):
        created = seed_company_categories(CompanyCategory)
        self.stdout.write(self.style.SUCCESS(
            f"Şirket kategorileri hazır. Yeni kayıt: {created}."
        ))
