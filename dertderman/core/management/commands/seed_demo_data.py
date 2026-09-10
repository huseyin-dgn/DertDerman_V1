from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from blog.models import Post
from companies.category_seed import COMPANY_CATEGORY_NAMES, seed_company_categories
from companies.models import Company, CompanyCategory, CompanyMembership, CompanyResponse
from complaints.models import (
    Complaint,
    ComplaintComment,
    ComplaintEvent,
    ComplaintLike,
    ComplaintReaction,
)


DEMO_PREFIX = "dd-demo-seed-"
DEMO_MARKER = "DD-DEMO-SEED-V1"

COMPANY_NAMES = (
    "MaviRota Lojistik", "KuzeySepet", "PusulaNet", "Işık Finans",
    "Duru Market", "KentHat Ulaşım", "ArmaOto", "UstaGaranti Teknoloji",
    "YeniDalga Telekom", "Ayaz Sigorta", "BilgeKöprü Eğitim", "ŞifaPınarı Sağlık",
    "RüyaYol Seyahat", "SofraBulut", "Modaİz", "Evora Yaşam",
    "VoltEnerji", "KamuKolay", "DijitalYuva", "PaketMart",
)

COMPLAINT_TITLES = (
    "Teslimat planlanan tarihte ulaşmadı",
    "Kargo takip bilgisi uzun süre güncellenmedi",
    "Hasarlı teslimat için dönüş bekliyorum",
    "Adres değişikliği talebim işlenmedi",
    "Teslimat saati bilgisi paylaşılmadı",
    "İade kargosu teslim alınmasına rağmen bekliyor",
    "Kurye iletişim süreci iyileştirilmeli",
    "Paket şubede gereğinden uzun süre kaldı",
    "Eksik ürün teslimatı için destek talebi",
    "Teslimat sonrası bilgilendirme gelmedi",
    "Siparişimdeki ürünlerden biri eksik geldi",
    "İade ücretinin hesaba geçmesini bekliyorum",
    "Faturama beklemediğim ek ücret yansıtıldı",
    "Ürün açıklaması ile gelen ürün uyuşmuyor",
    "Üyelik iptali için müşteri hizmetlerine ulaşamadım",
    "İnternet bağlantısı akşam saatlerinde yavaşlıyor",
    "Kart işlem bildirimi gecikmeli ulaştı",
    "Garanti kapsamındaki ürün için destek alamadım",
    "Toplu taşıma kartıma bakiye geç yükleniyor",
    "Servis randevusu planlanandan geç başladı",
)

BLOG_POSTS = (
    ("Etkili bir şikayet metni nasıl yazılır?", "Sorununuzu açık, ölçülü ve sonuç odaklı anlatmanın temel adımları."),
    ("Şirket yanıtlarını değerlendirirken nelere bakmalı?", "Resmi bir yanıtta çözüm, süre ve takip bilgisini ayırt etme rehberi."),
    ("Online alışverişte teslimat kaydı tutmanın önemi", "Sipariş ve teslimat sürecini sağlıklı takip etmek için pratik öneriler."),
    ("Çözüm sürecinde doğru iletişim dili", "Tüketici ve şirket arasında yapıcı iletişimi güçlendiren küçük ayrıntılar."),
    ("Abonelik iptalinde kontrol listesi", "İptal talebinden son faturaya kadar takip edilebilecek temel aşamalar."),
    ("İade sürecinde hangi bilgileri saklamalısınız?", "İade gönderisi ve ödeme takibi için yararlı kayıtların kısa özeti."),
    ("Dijital hizmetlerde güvenli hesap kullanımı", "Hesap güvenliği ve destek taleplerinde kişisel veriyi koruma önerileri."),
    ("Şikayet durumu ne anlama geliyor?", "İncelemede, yayında ve çözüldü durumlarının DertDerman'daki karşılığı."),
    ("Şirket profili metriklerini okuma rehberi", "Cevap oranı, çözüm oranı ve ortalama yanıt süresini doğru yorumlayın."),
    ("Topluluk etkileşiminde saygılı dil", "Yorum ve tepkilerle deneyimlere katkı sunarken gözetilecek ilkeler."),
)


class Command(BaseCommand):
    help = "Development/test ortamına güvenli ve idempotent DertDerman demo verisi ekler."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Yalnızca bu komutun işaretlediği demo kayıtlarını temizleyip yeniden oluşturur.")
        parser.add_argument("--allow-production", action="store_true", help="DEBUG=False ortamında çalıştırmayı açıkça onaylar.")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_production"]:
            raise CommandError("seed_demo_data DEBUG=False ortamında varsayılan olarak çalışmaz.")

        with transaction.atomic():
            if options["reset"]:
                self._reset()
            self._seed()

        counts = {
            "companies": Company.objects.filter(slug__startswith=DEMO_PREFIX).count(),
            "complaints": Complaint.objects.filter(description__contains=DEMO_MARKER).count(),
            "posts": Post.objects.filter(slug__startswith=DEMO_PREFIX).count(),
            "users": get_user_model().objects.filter(username__startswith=DEMO_PREFIX).count(),
        }
        self.stdout.write(self.style.SUCCESS(
            "Demo veri hazır: {companies} şirket, {complaints} şikayet, "
            "{posts} blog yazısı, {users} kullanıcı.".format(**counts)
        ))

    def _reset(self):
        Post.objects.filter(slug__startswith=DEMO_PREFIX).delete()
        Complaint.objects.filter(description__contains=DEMO_MARKER).delete()

        for company in Company.objects.filter(slug__startswith=DEMO_PREFIX):
            if not company.complaints.exists():
                company.delete()

        User = get_user_model()
        for user in User.objects.filter(username__startswith=DEMO_PREFIX):
            has_external_activity = (
                user.complaints.exists()
                or user.complaint_comments.exists()
                or user.complaint_likes.exists()
                or user.complaint_reactions.exists()
                or user.companyresponse_entries.exists()
            )
            if not has_external_activity:
                user.delete()

    def _seed(self):
        seed_company_categories(CompanyCategory)
        now = timezone.now()
        User = get_user_model()

        consumers = []
        for index in range(1, 6):
            user, _ = User.objects.update_or_create(
                username=f"{DEMO_PREFIX}user-{index:02d}",
                defaults={
                    "email": f"demo.user.{index:02d}@example.invalid",
                    "first_name": ("Deniz", "Ece", "Mert", "Selin", "Can")[index - 1],
                    "last_name": "Demo",
                    "user_type": User.UserType.USER,
                    "selected_avatar": f"avatar-{index}",
                    "is_active": True,
                },
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            User.objects.filter(pk=user.pk).update(date_joined=now - timedelta(days=90 - index * 5))
            consumers.append(user)

        agents = []
        for index in range(1, 6):
            user, _ = User.objects.update_or_create(
                username=f"{DEMO_PREFIX}company-{index:02d}",
                defaults={
                    "email": f"demo.company.{index:02d}@example.invalid",
                    "first_name": "Demo",
                    "last_name": f"Yetkili {index}",
                    "user_type": User.UserType.COMPANY,
                    "is_active": True,
                },
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            agents.append(user)

        categories = {category.name: category for category in CompanyCategory.objects.filter(name__in=COMPANY_CATEGORY_NAMES)}
        company_category_indexes = (4, 2, 8, 0, 3, 5, 6, 7, 1, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
        companies = []
        for index, name in enumerate(COMPANY_NAMES):
            company, _ = Company.objects.update_or_create(
                slug=f"{DEMO_PREFIX}company-{index + 1:02d}",
                defaults={
                    "name": name,
                    "description": f"{name}, DertDerman geliştirme ortamı için hazırlanmış kurgusal bir hizmet markasıdır.",
                    "website": f"https://demo-{index + 1:02d}.example.invalid",
                    "email": f"iletisim-{index + 1:02d}@example.invalid",
                    "phone": f"+90 212 555 {index + 1:02d} {index + 10:02d}",
                    "category": categories[COMPANY_CATEGORY_NAMES[company_category_indexes[index]]],
                    "is_verified": index < 12,
                    "approval_status": Company.ApprovalStatus.APPROVED,
                    "is_active": True,
                    "selected_avatar": f"company-{index % 8 + 1}",
                },
            )
            Company.objects.filter(pk=company.pk).update(created_at=now - timedelta(days=90 - index * 2))
            agent = agents[index % len(agents)]
            CompanyMembership.objects.update_or_create(
                user=agent,
                company=company,
                defaults={"role": CompanyMembership.Role.OWNER, "is_active": True},
            )
            companies.append(company)

        company_indexes = (0,) * 10 + (1,) * 5 + (2, 3, 4, 5, 6)
        statuses = (
            Complaint.Status.RESOLVED, Complaint.Status.RESOLVED, Complaint.Status.RESOLVED,
            Complaint.Status.RESOLVED, Complaint.Status.RESOLVED, Complaint.Status.RESOLVED,
            Complaint.Status.RESOLVED, Complaint.Status.PUBLISHED, Complaint.Status.PUBLISHED,
            Complaint.Status.PUBLISHED, Complaint.Status.RESOLVED, Complaint.Status.PUBLISHED,
            Complaint.Status.PUBLISHED, Complaint.Status.PUBLISHED, Complaint.Status.PUBLISHED,
            Complaint.Status.PUBLISHED, Complaint.Status.PUBLISHED, Complaint.Status.PUBLISHED,
            Complaint.Status.PENDING, Complaint.Status.PENDING,
        )
        complaints = []
        for index, (title, company_index, status) in enumerate(zip(COMPLAINT_TITLES, company_indexes, statuses)):
            owner = consumers[0] if index < 10 else consumers[(index - 9) % len(consumers)]
            company = companies[company_index]
            description = (
                f"{title}. Sürecin hangi aşamada olduğunu ve beklenen çözüm zamanını öğrenmek istiyorum. "
                f"Destek ekibinden açık bir bilgilendirme rica ediyorum.\n\n{DEMO_MARKER}"
            )
            complaint, _ = Complaint.objects.update_or_create(
                company=company,
                title=title,
                defaults={"user": owner, "description": description, "status": status, "withdrawn_at": None},
            )
            created_at = now - timedelta(days=87 - index * 3)
            Complaint.objects.filter(pk=complaint.pk).update(created_at=created_at, updated_at=created_at + timedelta(hours=8))
            ComplaintEvent.objects.filter(source_key=f"complaint:{complaint.pk}:created").update(occurred_at=created_at)
            initial_event_at = created_at + timedelta(hours=1)
            if status == Complaint.Status.PUBLISHED:
                initial_event_at = created_at + timedelta(hours=8)
            elif status == Complaint.Status.RESOLVED:
                initial_event_at = created_at + timedelta(days=3)
            ComplaintEvent.objects.filter(
                source_key=f"complaint:{complaint.pk}:initial:{status}"
            ).update(occurred_at=initial_event_at)
            if status in (Complaint.Status.PUBLISHED, Complaint.Status.RESOLVED):
                ComplaintEvent.objects.update_or_create(
                    source_key=f"{DEMO_PREFIX}complaint-{index + 1:02d}-published",
                    defaults={
                        "complaint": complaint,
                        "event_type": ComplaintEvent.Type.PUBLISHED,
                        "actor_type": ComplaintEvent.Actor.ADMIN,
                        "message": "Şikayet yayınlandı.",
                        "occurred_at": created_at + timedelta(hours=8),
                    },
                )
            complaints.append((complaint, created_at))

        response_indexes = tuple(range(10)) + (10, 11, 13, 15, 16)
        for response_number, complaint_index in enumerate(response_indexes):
            complaint, created_at = complaints[complaint_index]
            agent = agents[company_indexes[complaint_index] % len(agents)]
            response = CompanyResponse.objects.filter(
                complaint=complaint, company=complaint.company, author_user=agent,
            ).first()
            if response is None:
                response = CompanyResponse.objects.create(
                    complaint=complaint,
                    company=complaint.company,
                    author_user=agent,
                    body="Talebinizi inceledik. İlgili ekip kaydı kontrol ederek çözüm adımlarını sizinle paylaşacaktır.",
                )
            response_at = created_at + timedelta(hours=10 + response_number % 9)
            CompanyResponse.objects.filter(pk=response.pk).update(created_at=response_at, updated_at=response_at)
            ComplaintEvent.objects.update_or_create(
                source_key=f"{DEMO_PREFIX}response-{complaint_index + 1:02d}",
                defaults={
                    "complaint": complaint,
                    "event_type": ComplaintEvent.Type.COMPANY_RESPONDED,
                    "actor_type": ComplaintEvent.Actor.COMPANY,
                    "message": "Şirket resmi yanıtını paylaştı.",
                    "occurred_at": response_at,
                },
            )

        public_complaints = [item[0] for item in complaints if item[0].status != Complaint.Status.PENDING]
        for index, complaint in enumerate(public_complaints[:12]):
            actor = consumers[(index + 1) % len(consumers)]
            if actor.pk != complaint.user_id:
                ComplaintLike.objects.get_or_create(complaint=complaint, user=actor)
                ComplaintReaction.objects.update_or_create(
                    complaint=complaint,
                    user=actor,
                    defaults={"reaction_type": ("👍", "❤️", "😮", "😕")[index % 4]},
                )
        for index, complaint in enumerate(public_complaints[:8]):
            actor = consumers[(index + 2) % len(consumers)]
            ComplaintComment.objects.update_or_create(
                complaint=complaint,
                author_user=actor,
                body=f"Benzer bir süreç yaşamıştım; paylaşılan çözüm adımlarını takip etmek faydalı olabilir. {DEMO_MARKER}",
            )

        for index, (title, excerpt) in enumerate(BLOG_POSTS):
            published_at = now - timedelta(days=84 - index * 6)
            post, _ = Post.objects.update_or_create(
                slug=f"{DEMO_PREFIX}post-{index + 1:02d}",
                defaults={
                    "title": title,
                    "author": consumers[index % len(consumers)],
                    "excerpt": excerpt,
                    "content": (
                        f"{excerpt}\n\nDeneyiminizi tarih, işlem ve beklediğiniz çözümle birlikte aktarmak iletişimi kolaylaştırır. "
                        f"Kişisel verilerinizi public metne eklemeden süreci anlaşılır biçimde özetleyin.\n\n{DEMO_MARKER}"
                    ),
                    "status": Post.Status.PUBLISHED,
                    "published_at": published_at,
                },
            )
            Post.objects.filter(pk=post.pk).update(
                created_at=published_at - timedelta(days=1),
                updated_at=published_at,
                published_at=published_at,
            )
