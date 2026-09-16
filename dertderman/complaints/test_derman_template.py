from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import (
    Company,
    CompanyMembership,
    CompanySubscription,
)

from .models import (
    Complaint,
    DermanCompanyResponse,
    DermanPost,
)


User = get_user_model()


class DermanTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="derman-template-owner",
            email="derman-template-owner@example.com",
            user_type=User.UserType.USER,
        )

        cls.viewer = User.objects.create_user(
            username="derman-template-viewer",
            email="derman-template-viewer@example.com",
            user_type=User.UserType.USER,
        )

        cls.derman_author = User.objects.create_user(
            username="derman-template-author",
            email="derman-template-author@example.com",
            user_type=User.UserType.USER,
        )

        cls.company_user = User.objects.create_user(
            username="derman-template-company",
            email="derman-template-company@example.com",
            user_type=User.UserType.COMPANY,
        )

        cls.company = Company.objects.create(
            name="Derman Template Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        cls.complaint = Complaint.objects.create(
            user=cls.owner,
            company=cls.company,
            title="Derman template şikayeti",
            description=(
                "Derman template testleri için "
                "yeterince uzun bir açıklama."
            ),
            status=Complaint.Status.PUBLISHED,
        )

        cls.derman = DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.derman_author,
            body=(
                "Sadece yetkili görüntüleyicilerin "
                "görebilmesi gereken benzersiz "
                "Derman template içeriği."
            ),
            status=DermanPost.Status.PUBLISHED,
            published_at=timezone.now(),
        )

        cls.url = reverse(
            "complaints:public_detail",
            args=[cls.complaint.pk],
        )

    def _create_company_response(self):
        return DermanCompanyResponse.objects.create(
            derman=self.derman,
            company=self.company,
            author_user=self.company_user,
            body=(
                "Bu metin Derman için yayınlanan "
                "benzersiz resmi şirket yanıtıdır."
            ),
        )

    def _grant_pro(self, role):
        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=role,
            is_active=True,
        )

        CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=(
                CompanySubscription.BillingPeriod.MONTHLY
            ),
            is_active=True,
            current_period_end=(
                timezone.now()
                + timedelta(days=30)
            ),
        )

    def _grant_unrelated_company_access(self, *, pro=False):
        unrelated_company = Company.objects.create(
            name="Unrelated Derman Template Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        CompanyMembership.objects.create(
            user=self.company_user,
            company=unrelated_company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        if pro:
            CompanySubscription.objects.create(
                company=unrelated_company,
                plan=CompanySubscription.Plan.PRO,
                billing_period=(
                    CompanySubscription.BillingPeriod.MONTHLY
                ),
                is_active=True,
                current_period_end=(
                    timezone.now()
                    + timedelta(days=30)
                ),
            )

    def test_anonymous_sees_count_but_not_derman_body(self):
        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "1 yayınlanmış Derman",
        )

        self.assertNotContains(
            response,
            self.derman.body,
        )

    def test_user_sees_body_create_form_and_reactions(self):
        self.client.force_login(
            self.viewer
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            self.derman.body,
        )

        self.assertContains(
            response,
            reverse(
                "complaints:derman_create",
                args=[self.complaint.pk],
            ),
        )

        self.assertContains(
            response,
            reverse(
                "complaints:derman_react",
                args=[
                    self.complaint.pk,
                    self.derman.pk,
                ],
            ),
        )

        self.assertContains(
            response,
            'name="confirm_no_edit"',
            html=False,
        )

    def test_complaint_owner_sees_body_but_no_create_form(self):
        self.client.force_login(
            self.owner
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            self.derman.body,
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_create",
                args=[self.complaint.pk],
            ),
        )

    def test_derman_author_gets_withdraw_not_reaction_controls(self):
        self.client.force_login(
            self.derman_author
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            reverse(
                "complaints:derman_withdraw",
                args=[
                    self.complaint.pk,
                    self.derman.pk,
                ],
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_react",
                args=[
                    self.complaint.pk,
                    self.derman.pk,
                ],
            ),
        )

    def test_standard_company_gets_paywall_without_body(self):
        company_response = (
            self._create_company_response()
        )

        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        self.client.force_login(
            self.company_user
        )

        response = self.client.get(
            self.url
        )

        self.assertNotContains(
            response,
            self.derman.body,
        )

        self.assertNotContains(
            response,
            company_response.body,
        )

        self.assertContains(
            response,
            "DertDerman Pro",
        )

        self.assertContains(
            response,
            "1 yayınlanmış Derman",
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_create",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_update",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

    def test_unrelated_standard_company_sees_only_public_count(self):
        company_response = self._create_company_response()
        self._grant_unrelated_company_access()

        self.client.force_login(self.company_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 yayınlanmış Derman")
        self.assertNotContains(response, self.derman.body)
        self.assertNotContains(response, self.derman_author.username)
        self.assertNotContains(response, company_response.body)
        self.assertNotContains(response, "DertDerman Pro")
        self.assertNotContains(response, "Pro'yu İncele")
        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_company_response_create",
                kwargs={"derman_pk": self.derman.pk},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_company_response_update",
                kwargs={"derman_pk": self.derman.pk},
            ),
        )

    def test_unrelated_pro_company_sees_only_public_count(self):
        company_response = self._create_company_response()
        self._grant_unrelated_company_access(pro=True)

        self.client.force_login(self.company_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 yayınlanmış Derman")
        self.assertNotContains(response, self.derman.body)
        self.assertNotContains(response, self.derman_author.username)
        self.assertNotContains(response, company_response.body)
        self.assertNotContains(response, "DertDerman Pro")
        self.assertNotContains(response, "Pro'yu İncele")
        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_react",
                args=[self.complaint.pk, self.derman.pk],
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_company_response_create",
                kwargs={"derman_pk": self.derman.pk},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_company_response_update",
                kwargs={"derman_pk": self.derman.pk},
            ),
        )

    def test_pro_company_with_exact_membership_sees_body(self):
        self._grant_pro(
            CompanyMembership.Role.MANAGER
        )

        self.client.force_login(
            self.company_user
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            self.derman.body,
        )

        self.assertNotContains(
            response,
            "DertDerman Pro'yu İncele",
        )

    def test_resolved_complaint_is_visible_but_has_no_new_mutation_controls(
        self,
    ):
        self.complaint.status = Complaint.Status.RESOLVED
        self.complaint.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        self.client.force_login(
            self.viewer
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            self.derman.body,
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_create",
                args=[self.complaint.pk],
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_react",
                args=[
                    self.complaint.pk,
                    self.derman.pk,
                ],
            ),
        )

    def test_suspended_user_can_view_but_gets_no_derman_mutation_controls(
        self,
    ):
        self.viewer.is_suspended = True
        self.viewer.save(
            update_fields=(
                "is_suspended",
            )
        )

        self.client.force_login(
            self.viewer
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            self.derman.body,
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_create",
                args=[self.complaint.pk],
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:derman_react",
                args=[
                    self.complaint.pk,
                    self.derman.pk,
                ],
            ),
        )

    def test_user_sees_official_company_response_without_company_controls(
        self,
    ):
        company_response = (
            self._create_company_response()
        )

        self.client.force_login(
            self.viewer
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            "Resmi Şirket Yanıtı",
        )

        self.assertContains(
            response,
            company_response.body,
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_create",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_update",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

    def test_pro_manager_without_response_gets_create_control(
        self,
    ):
        self._grant_pro(
            CompanyMembership.Role.MANAGER
        )

        self.client.force_login(
            self.company_user
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            "Resmi Yanıt Ver",
        )

        self.assertContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_create",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_update",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )
    def test_pro_manager_with_response_gets_update_control(
        self,
    ):
        company_response = (
            self._create_company_response()
        )

        self._grant_pro(
            CompanyMembership.Role.MANAGER
        )

        self.client.force_login(
            self.company_user
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            company_response.body,
        )

        self.assertContains(
            response,
            "Yanıtı Düzenle",
        )

        update_url = reverse(
            (
                "complaints:"
                "derman_company_response_update"
            ),
            kwargs={
                "derman_pk": self.derman.pk,
            },
        )

        create_url = reverse(
            (
                "complaints:"
                "derman_company_response_create"
            ),
            kwargs={
                "derman_pk": self.derman.pk,
            },
        )

        self.assertContains(
            response,
            f'action="{update_url}"',
            html=False,
        )

        self.assertNotContains(
            response,
            f'action="{create_url}"',
            html=False,
        )

    def test_pro_support_sees_response_but_gets_no_company_controls(
        self,
    ):
        company_response = (
            self._create_company_response()
        )

        self._grant_pro(
            CompanyMembership.Role.SUPPORT
        )

        self.client.force_login(
            self.company_user
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            company_response.body,
        )

        self.assertNotContains(
            response,
            "Resmi Yanıt Ver",
        )

        self.assertNotContains(
            response,
            "Yanıtı Düzenle",
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_create",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_update",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

    def test_resolved_pro_manager_sees_response_without_company_mutation_controls(
        self,
    ):
        company_response = (
            self._create_company_response()
        )

        self._grant_pro(
            CompanyMembership.Role.MANAGER
        )

        self.complaint.status = (
            Complaint.Status.RESOLVED
        )

        self.complaint.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        self.client.force_login(
            self.company_user
        )

        response = self.client.get(
            self.url
        )

        self.assertContains(
            response,
            company_response.body,
        )

        self.assertNotContains(
            response,
            "Resmi Yanıt Ver",
        )

        self.assertNotContains(
            response,
            "Yanıtı Düzenle",
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_create",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "complaints:"
                "derman_company_response_update",
                kwargs={
                    "derman_pk": self.derman.pk,
                },
            ),
        )
