from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company, CompanyMembership, CompanyNotification, CompanyResponse
from notifications.models import Notification

from .models import Complaint, ComplaintEvent


User = get_user_model()


class UserPanelV2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="panel-owner", email="panel-owner@example.com", user_type="USER")
        cls.other = User.objects.create_user(username="panel-other", email="panel-other@example.com", user_type="USER")
        cls.admin = User.objects.create_user(username="panel-admin", email="panel-admin@example.com", user_type="ADMIN")
        cls.agent = User.objects.create_user(username="panel-agent", email="panel-agent@example.com", user_type="COMPANY")
        cls.company = Company.objects.create(name="Panel Teknoloji", is_verified=True)
        CompanyMembership.objects.create(user=cls.agent, company=cls.company, role="OWNER")

    def setUp(self):
        self.client.force_login(self.owner)

    def complaint(self, *, owner=None, status=Complaint.Status.PENDING, title="Panel sipariş sorunu"):
        return Complaint.objects.create(
            user=owner or self.owner,
            company=self.company,
            status=status,
            title=title,
            description="Kullanıcı paneli testi için yeterince uzun şikayet açıklaması.",
        )

    def test_dashboard_metrics_previews_are_real_owner_scoped_and_bounded(self):
        records = [
            self.complaint(status=Complaint.Status.PENDING, title="İncelemedeki kayıt"),
            self.complaint(status=Complaint.Status.PUBLISHED, title="Yanıtlanan kayıt"),
            self.complaint(status=Complaint.Status.RESOLVED, title="Çözülen kayıt"),
        ]
        CompanyResponse.objects.create(company=self.company, complaint=records[1], author_user=self.agent, body="Şirket yanıtı")
        self.complaint(owner=self.other, title="Başka kullanıcının gizli kaydı")
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.context["metrics"]["total"], 3)
        self.assertEqual(response.context["metrics"]["pending"], 1)
        self.assertEqual(response.context["metrics"]["answered"], 1)
        self.assertEqual(response.context["metrics"]["resolved"], 1)
        self.assertLessEqual(len(response.context["recent_complaints"]), 5)
        self.assertLessEqual(len(response.context["recent_notifications"]), 5)
        self.assertNotContains(response, "Başka kullanıcının gizli kaydı")

    def test_list_is_six_per_page_newest_first_searchable_and_filterable(self):
        records = [self.complaint(title=f"Sipariş kaydı {index:02d}") for index in range(13)]
        tied = timezone.now()
        Complaint.objects.filter(pk__in=[item.pk for item in records]).update(created_at=tied)
        first = self.client.get(reverse("complaints:list"))
        second = self.client.get(reverse("complaints:list"), {"page": 2})
        third = self.client.get(reverse("complaints:list"), {"page": 3})
        self.assertEqual([len(first.context["page_obj"]), len(second.context["page_obj"]), len(third.context["page_obj"])], [6, 6, 1])
        seen = list(first.context["page_obj"]) + list(second.context["page_obj"]) + list(third.context["page_obj"])
        self.assertEqual([item.pk for item in seen], [item.pk for item in reversed(records)])
        search = self.client.get(reverse("complaints:list"), {"q": "12", "status": "all"})
        self.assertEqual(list(search.context["page_obj"]), [records[12]])
        self.assertContains(search, "q=12")

        published = records[0]
        published.status = Complaint.Status.PUBLISHED
        published.save()
        CompanyResponse.objects.create(company=self.company, complaint=published, author_user=self.agent, body="Yanıt metni")
        answered = self.client.get(reverse("complaints:list"), {"status": "answered"})
        self.assertEqual(list(answered.context["page_obj"]), [published])
        self.assertContains(answered, "Şirket cevapladı")

    def test_user_resolve_records_timeline_and_notifies_company_without_self_duplicate(self):
        complaint = self.complaint()
        self.client.force_login(self.admin)
        self.client.post(reverse("adminx:complaint_publish", args=[complaint.pk]))
        CompanyResponse.objects.create(company=self.company, complaint=complaint, author_user=self.agent, body="Çözüm yanıtı")
        self.client.force_login(self.owner)
        response = self.client.post(reverse("complaints:resolve", args=[complaint.pk]))
        self.assertRedirects(response, reverse("complaints:detail", args=[complaint.pk]))
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.RESOLVED)
        events = list(complaint.timeline_events.values_list("event_type", flat=True))
        for event_type in ["CREATED", "PENDING", "PUBLISHED", "COMPANY_RESPONDED", "RESOLVED"]:
            self.assertIn(event_type, events)
        resolved = complaint.timeline_events.get(event_type=ComplaintEvent.Type.RESOLVED)
        self.assertEqual(resolved.actor_type, ComplaintEvent.Actor.USER)
        self.assertEqual(resolved.message, "Kullanıcı sorunun çözüldüğünü onayladı.")
        self.assertEqual(complaint.company_notifications.filter(kind=CompanyNotification.Kind.RESOLVED).count(), 1)
        self.assertEqual(Notification.objects.filter(complaint=complaint, notification_type="RESOLVED").count(), 0)
        detail = self.client.get(reverse("complaints:detail", args=[complaint.pk]))
        for label in ["Şikayet oluşturuldu", "Yayınlandı", "Şirket cevapladı", "Çözüldü"]:
            self.assertContains(detail, label)

    def test_admin_resolve_notifies_user_and_company_once(self):
        complaint = self.complaint(status=Complaint.Status.PUBLISHED)
        self.client.force_login(self.admin)
        route = reverse("adminx:complaint_resolve", args=[complaint.pk])
        self.assertEqual(self.client.get(route).status_code, 405)
        self.assertEqual(self.client.post(route).status_code, 302)
        self.assertEqual(self.client.post(route).status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.RESOLVED)
        event = complaint.timeline_events.get(source_key=f"complaint:{complaint.pk}:resolved:admin")
        self.assertEqual(event.message, "Yönetici tarafından çözüldü olarak işaretlendi.")
        self.assertEqual(Notification.objects.filter(complaint=complaint, notification_type="RESOLVED").count(), 1)
        self.assertEqual(complaint.company_notifications.filter(kind="RESOLVED").count(), 1)

    def test_resolve_role_idor_and_csrf_enforcement(self):
        own = self.complaint(status=Complaint.Status.PUBLISHED)
        foreign = self.complaint(owner=self.other, status=Complaint.Status.PUBLISHED, title="Başkasının yayındaki kaydı")
        self.assertEqual(self.client.get(reverse("complaints:resolve", args=[own.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse("complaints:resolve", args=[foreign.pk])).status_code, 404)

        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(reverse("complaints:resolve", args=[own.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("adminx:complaint_resolve", args=[own.pk])).status_code, 403)
        own.refresh_from_db()
        self.assertEqual(own.status, Complaint.Status.PUBLISHED)

        for user, route in [
            (self.owner, reverse("complaints:resolve", args=[own.pk])),
            (self.admin, reverse("adminx:complaint_resolve", args=[own.pk])),
        ]:
            csrf_client = Client(enforce_csrf_checks=True)
            csrf_client.force_login(user)
            self.assertEqual(csrf_client.post(route).status_code, 403)
        own.refresh_from_db()
        self.assertEqual(own.status, Complaint.Status.PUBLISHED)
