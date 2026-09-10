from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from companies.models import Company, CompanyMembership, CompanyResponse
from complaints.models import (
    Complaint, ComplaintComment, ComplaintEvent, ComplaintLike, ComplaintReaction,
)
from notifications.models import Notification


User = get_user_model()


def image_upload(name="photo.png", size=(80, 80), image_format="PNG", content_type="image/png"):
    output = BytesIO()
    Image.new("RGB", size, "#2780b8").save(output, image_format)
    return SimpleUploadedFile(name, output.getvalue(), content_type=content_type)


@override_settings(MEDIA_ROOT=tempfile.gettempdir() + "/dertderman-product-tests")
class ProductRefinementSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="owner-v2", email="owner-v2@example.com", password="StrongPass2026!", user_type="USER")
        cls.other = User.objects.create_user(username="other-v2", email="other-v2@example.com", password="StrongPass2026!", user_type="USER")
        cls.admin = User.objects.create_user(username="admin-v2", email="admin-v2@example.com", password="StrongPass2026!", user_type="ADMIN", is_staff=True)
        cls.company_user = User.objects.create_user(username="company-v2", email="company-v2@example.com", password="StrongPass2026!", user_type="COMPANY")
        cls.company = Company.objects.create(name="Product V2 Company", is_verified=True)
        cls.complaint = Complaint.objects.create(user=cls.owner, company=cls.company, title="Düzenlenebilir şikayet", description="Düzenleme testleri için yeterince uzun açıklama.", status="PUBLISHED")

    def profile_payload(self, **extra):
        return {"first_name": "Ada", "last_name": "Yılmaz", "email": self.owner.email, "phone": "5551112233", "selected_avatar": "avatar-1", **extra}

    def test_user_avatar_selection_and_cross_user_isolation_without_upload(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("accounts:profile_edit"), self.profile_payload(selected_avatar="avatar-7"))
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.selected_avatar, "avatar-7")

        upload = image_upload("unsafe original name.png", size=(2400, 1800))
        response = self.client.post(reverse("accounts:profile_edit"), self.profile_payload(profile_image=upload, user_id=self.other.pk, selected_avatar="avatar-8"))
        self.assertRedirects(response, reverse("accounts:profile"))
        self.owner.refresh_from_db(); self.other.refresh_from_db()
        self.assertFalse(self.owner.profile_image)
        self.assertFalse(self.other.profile_image)
        self.assertEqual(self.owner.selected_avatar, "avatar-8")
        self.assertNotContains(self.client.get(reverse("accounts:profile_edit")), 'type="file"')

    def test_user_avatar_rejects_invalid_key_and_arbitrary_path(self):
        self.client.force_login(self.owner)
        for value in ("../companies/company-1", "/static/private.svg", "avatar-21"):
            with self.subTest(value=value):
                response = self.client.post(reverse("accounts:profile_edit"), self.profile_payload(selected_avatar=value))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors["selected_avatar"])

    def test_company_logo_owner_manager_allowed_support_blocked_and_idor_ignored(self):
        other_company = Company.objects.create(name="Other Company")
        owner_client = None
        for role, expected in (("OWNER", 302), ("MANAGER", 302), ("SUPPORT", 403)):
            user = User.objects.create_user(username=f"role-{role.lower()}", email=f"{role.lower()}@example.com", password="StrongPass2026!", user_type="COMPANY")
            CompanyMembership.objects.create(user=user, company=self.company, role=role)
            client = Client(); client.force_login(user)
            if role == "OWNER":
                owner_client = client
            response = client.post(reverse("companies:profile"), {"name": self.company.name, "company_id": other_company.pk, "logo": image_upload(f"{role}.png")})
            with self.subTest(role=role):
                self.assertEqual(response.status_code, expected)
        self.company.refresh_from_db(); other_company.refresh_from_db()
        self.assertTrue(self.company.logo)
        self.assertFalse(other_company.logo)
        response = owner_client.post(reverse("companies:profile"), {"name": self.company.name, "logo-clear": "on"})
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)

    def test_arbitrary_emoji_update_toggle_validation_and_notification_deduplication(self):
        self.client.force_login(self.other)
        url = reverse("complaints:react", args=[self.complaint.pk])
        self.client.post(url, {"reaction_type": "😀"})
        self.client.post(url, {"reaction_type": "😂"})
        self.assertEqual(ComplaintReaction.objects.get(complaint=self.complaint, user=self.other).reaction_type, "😂")
        self.assertEqual(ComplaintReaction.objects.filter(complaint=self.complaint, user=self.other).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient_user=self.owner, notification_type="REACTION").count(), 1)
        self.client.post(url, {"reaction_type": "😂"})
        self.assertFalse(ComplaintReaction.objects.filter(complaint=self.complaint, user=self.other).exists())
        for invalid in ("hello", "<script>", "😀😂", "🖕"):
            self.client.post(url, {"reaction_type": invalid})
            self.assertFalse(ComplaintReaction.objects.filter(complaint=self.complaint, user=self.other).exists())

    def test_reaction_never_self_notifies(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("complaints:react", args=[self.complaint.pk]), {"reaction_type": "❤️"})
        self.assertFalse(Notification.objects.filter(recipient_user=self.owner, notification_type="REACTION").exists())

    def test_edit_permissions_status_timeline_and_moderation_notification(self):
        url = reverse("complaints:edit", args=[self.complaint.pk])
        self.assertRedirects(self.client.get(url), reverse("accounts:login") + f"?next={url}")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.company_user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.post(url, {"company": self.company.pk, "title": "Güncellenen şikayet", "description": "Güncellenmiş ve yeterince uzun şikayet açıklaması."})
        self.assertRedirects(response, reverse("complaints:detail", args=[self.complaint.pk]))
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Complaint.Status.PENDING)
        self.assertTrue(self.complaint.timeline_events.filter(event_type=ComplaintEvent.Type.EDITED, message="Şikayet kullanıcı tarafından düzenlendi ve yeniden incelemeye gönderildi.").exists())
        self.assertTrue(Notification.objects.filter(recipient_user=self.admin, notification_type="MODERATION", complaint=self.complaint).exists())

    def test_pending_rejected_and_resolved_edit_policy(self):
        self.client.force_login(self.owner)
        for status, expected_status in (("PENDING", "PENDING"), ("REJECTED", "PENDING")):
            item = Complaint.objects.create(user=self.owner, company=self.company, title=f"{status} şikayet", description="Politika testi için yeterince uzun açıklama.", status=status)
            response = self.client.post(reverse("complaints:edit", args=[item.pk]), {"company": self.company.pk, "title": f"{status} güncellendi", "description": "Politika için güncellenmiş yeterince uzun açıklama."})
            self.assertEqual(response.status_code, 302); item.refresh_from_db(); self.assertEqual(item.status, expected_status)
        resolved = Complaint.objects.create(user=self.owner, company=self.company, title="Resolved şikayet", description="Çözülen kayıt için yeterince uzun açıklama.", status="RESOLVED")
        self.assertEqual(self.client.get(reverse("complaints:edit", args=[resolved.pk])).status_code, 403)

    def test_withdraw_is_post_only_owner_scoped_csrf_protected_and_preserves_history(self):
        reply = CompanyResponse.objects.create(complaint=self.complaint, company=self.company, author_user=self.company_user, body="Yanıt korunacak.")
        comment = ComplaintComment.objects.create(complaint=self.complaint, author_user=self.other, body="Yorum korunacak.")
        like = ComplaintLike.objects.create(complaint=self.complaint, user=self.other)
        reaction = ComplaintReaction.objects.create(complaint=self.complaint, user=self.other, reaction_type="😀")
        url = reverse("complaints:withdraw", args=[self.complaint.pk])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True); csrf_client.force_login(self.owner)
        csrf_client.get(reverse("complaints:detail", args=[self.complaint.pk]))
        self.assertEqual(csrf_client.post(url).status_code, 403)
        token = csrf_client.cookies["csrftoken"].value
        self.assertEqual(csrf_client.post(url, {"csrfmiddlewaretoken": token}).status_code, 302)
        self.complaint.refresh_from_db()
        self.assertIsNotNone(self.complaint.withdrawn_at)
        self.assertEqual(self.client.get(reverse("complaints:public_detail", args=[self.complaint.pk])).status_code, 404)
        for model, pk in ((CompanyResponse, reply.pk), (ComplaintComment, comment.pk), (ComplaintLike, like.pk), (ComplaintReaction, reaction.pk)):
            self.assertTrue(model.objects.filter(pk=pk).exists())
        self.assertTrue(self.complaint.timeline_events.filter(event_type=ComplaintEvent.Type.WITHDRAWN).exists())

        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
