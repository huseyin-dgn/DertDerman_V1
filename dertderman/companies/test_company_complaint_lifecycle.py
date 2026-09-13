from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from complaints.models import Complaint

from companies.models import (
    Company,
    CompanyCategory,
    CompanyMembership,
    CompanyNotification,
    CompanyResponse,
    CompanySubscription,
    InternalCompanyNote,
)
from companies.panel_services import (
    create_company_entry,
)


User = get_user_model()


class CompanyComplaintLifecycleTests(TestCase):

    def setUp(self):
        self.company_user = (
            User.objects.create_user(
                username="lifecycle-company",
                email="lifecycle-company@example.com",
                password="StrongPass2026!",
                user_type=User.UserType.COMPANY,
                is_verified=True,
            )
        )

        self.consumer = (
            User.objects.create_user(
                username="lifecycle-user",
                email="lifecycle-user@example.com",
                password="StrongPass2026!",
                user_type=User.UserType.USER,
                is_verified=True,
            )
        )

        category = (
            CompanyCategory.objects.create(
                name="Lifecycle Category",
            )
        )

        self.company = (
            Company.objects.create(
                name="Lifecycle Company",
                category=category,
                is_active=True,
                is_verified=True,
                approval_status=(
                    Company.ApprovalStatus.APPROVED
                ),
            )
        )

        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=(
                CompanySubscription
                .BillingPeriod
                .MONTHLY
            ),
            is_active=True,
            current_period_end=None,
        )

        self.client.force_login(
            self.company_user
        )

    def make_complaint(
        self,
        *,
        status,
        title,
        withdrawn=False,
        removed_for_violation=False,
    ):
        complaint = Complaint.objects.create(
            user=self.consumer,
            company=self.company,
            title=title,
            description=(
                "Bu sikayet lifecycle testleri "
                "icin yeterince uzun bir aciklamadir."
            ),
            status=status,
            removed_for_violation=(
                removed_for_violation
            ),
        )

        if withdrawn:
            complaint.withdrawn_at = timezone.now()
            complaint.save(
                update_fields=(
                    "withdrawn_at",
                    "updated_at",
                )
            )

        return complaint

    def response_url(self, complaint):
        return reverse(
            "companies:response_create",
            kwargs={"pk": complaint.pk},
        )

    def note_url(self, complaint):
        return reverse(
            "companies:note_create",
            kwargs={"pk": complaint.pk},
        )

    def detail_url(self, complaint):
        return reverse(
            "companies:complaint_detail",
            kwargs={"pk": complaint.pk},
        )

    def test_pending_complaint_is_hidden_from_company(self):
        complaint = self.make_complaint(
            status=Complaint.Status.PENDING,
            title="Pending complaint lifecycle",
        )

        list_response = self.client.get(
            reverse("companies:complaint_list")
        )

        self.assertNotContains(
            list_response,
            complaint.title,
        )

        detail_response = self.client.get(
            self.detail_url(complaint)
        )

        self.assertEqual(
            detail_response.status_code,
            404,
        )

    def test_rejected_complaint_is_hidden_from_company(self):
        complaint = self.make_complaint(
            status=Complaint.Status.REJECTED,
            title="Rejected complaint lifecycle",
        )

        list_response = self.client.get(
            reverse("companies:complaint_list")
        )

        self.assertNotContains(
            list_response,
            complaint.title,
        )

        detail_response = self.client.get(
            self.detail_url(complaint)
        )

        self.assertEqual(
            detail_response.status_code,
            404,
        )

    def test_published_complaint_is_interactive_for_pro(self):
        complaint = self.make_complaint(
            status=Complaint.Status.PUBLISHED,
            title="Published complaint lifecycle",
        )

        detail_response = self.client.get(
            self.detail_url(complaint)
        )

        self.assertEqual(
            detail_response.status_code,
            200,
        )

        self.assertContains(
            detail_response,
            "Şirket cevabı yazın",
        )

        response = self.client.post(
            self.response_url(complaint),
            {
                "body": (
                    "Yayindaki sikayete verilen "
                    "kurumsal test cevabi."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            CompanyResponse.objects.filter(
                complaint=complaint,
                company=self.company,
            ).exists()
        )

    def test_resolved_complaint_is_visible_but_read_only(self):
        complaint = self.make_complaint(
            status=Complaint.Status.RESOLVED,
            title="Resolved complaint lifecycle",
        )

        detail = self.client.get(
            self.detail_url(complaint)
        )

        self.assertEqual(
            detail.status_code,
            200,
        )

        self.assertContains(
            detail,
            "SALT OKUNUR KAYIT",
        )

        response = self.client.post(
            self.response_url(complaint),
            {
                "body": "Bu cevap yazilmamali.",
            },
        )

        note = self.client.post(
            self.note_url(complaint),
            {
                "body": "Bu not yazilmamali.",
            },
        )

        self.assertEqual(
            response.status_code,
            409,
        )

        self.assertEqual(
            note.status_code,
            409,
        )

        self.assertFalse(
            CompanyResponse.objects.filter(
                complaint=complaint
            ).exists()
        )

        self.assertFalse(
            InternalCompanyNote.objects.filter(
                complaint=complaint
            ).exists()
        )

    def test_removed_complaint_is_visible_but_read_only(self):
        complaint = self.make_complaint(
            status=Complaint.Status.REMOVED,
            title="Removed complaint lifecycle",
            removed_for_violation=True,
        )

        detail = self.client.get(
            self.detail_url(complaint)
        )

        self.assertEqual(
            detail.status_code,
            200,
        )

        self.assertContains(
            detail,
            "SALT OKUNUR KAYIT",
        )

        self.assertEqual(
            self.client.post(
                self.response_url(complaint),
                {"body": "No response"},
            ).status_code,
            409,
        )

    def test_withdrawn_complaint_is_visible_but_read_only(self):
        complaint = self.make_complaint(
            status=Complaint.Status.PUBLISHED,
            title="Withdrawn complaint lifecycle",
            withdrawn=True,
        )

        detail = self.client.get(
            self.detail_url(complaint)
        )

        self.assertEqual(
            detail.status_code,
            200,
        )

        self.assertContains(
            detail,
            "geri çekildi",
        )

        self.assertEqual(
            self.client.post(
                self.note_url(complaint),
                {"body": "No note"},
            ).status_code,
            409,
        )

    def test_service_rejects_hidden_pending_complaint(self):
        complaint = self.make_complaint(
            status=Complaint.Status.PENDING,
            title="Pending service bypass",
        )

        with self.assertRaises(
            ValidationError
        ):
            create_company_entry(
                user=self.company_user,
                company_id=self.company.pk,
                complaint_id=complaint.pk,
                body=(
                    "Servis katmanindan "
                    "bypass deneniyor."
                ),
                internal=False,
            )

    def test_pending_creation_does_not_notify_company(self):
        complaint = self.make_complaint(
            status=Complaint.Status.PENDING,
            title="Pending notification privacy",
        )

        self.assertFalse(
            CompanyNotification.objects.filter(
                company=self.company,
                complaint=complaint,
            ).exists()
        )

        complaint.status = (
            Complaint.Status.PUBLISHED
        )

        complaint.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        self.assertTrue(
            CompanyNotification.objects.filter(
                company=self.company,
                complaint=complaint,
                kind=(
                    CompanyNotification
                    .Kind
                    .PUBLISHED
                ),
            ).exists()
        )
