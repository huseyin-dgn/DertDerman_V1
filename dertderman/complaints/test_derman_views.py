from django.contrib.auth import (
    get_user_model,
)
from django.test import (
    Client,
    TestCase,
)
from django.urls import reverse

from companies.models import Company

from .models import (
    Complaint,
    DermanPost,
    DermanReaction,
)


User = get_user_model()


class DermanViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = (
            User.objects.create_user(
                username="derman-view-owner",
                email=(
                    "derman-view-owner"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.author = (
            User.objects.create_user(
                username="derman-view-author",
                email=(
                    "derman-view-author"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.other = (
            User.objects.create_user(
                username="derman-view-other",
                email=(
                    "derman-view-other"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.company_user = (
            User.objects.create_user(
                username=(
                    "derman-view-company"
                ),
                email=(
                    "derman-view-company"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.company = Company.objects.create(
            name="Derman View Company",
        )

        cls.complaint = (
            Complaint.objects.create(
                user=cls.owner,
                company=cls.company,
                title=(
                    "Derman endpoint testi"
                ),
                description=(
                    "Derman endpoint testleri "
                    "için yeterince uzun "
                    "şikayet açıklaması."
                ),
                status=(
                    Complaint.Status.PUBLISHED
                ),
            )
        )

    def create_url(
        self,
        complaint=None,
    ):
        complaint = (
            complaint
            or self.complaint
        )

        return reverse(
            "complaints:derman_create",
            args=[complaint.pk],
        )

    def withdraw_url(
        self,
        derman,
        complaint=None,
    ):
        complaint = (
            complaint
            or self.complaint
        )

        return reverse(
            "complaints:derman_withdraw",
            args=[
                complaint.pk,
                derman.pk,
            ],
        )

    def reaction_url(
        self,
        derman,
        complaint=None,
    ):
        complaint = (
            complaint
            or self.complaint
        )

        return reverse(
            "complaints:derman_react",
            args=[
                complaint.pk,
                derman.pk,
            ],
        )

    def create_published_derman(
        self,
        *,
        author=None,
    ):
        return (
            DermanPost.objects.create(
                complaint=self.complaint,
                author_user=(
                    author
                    or self.author
                ),
                body=(
                    "Bu yayınlanmış Derman "
                    "endpoint testleri için "
                    "yeterli uzunluktadır."
                ),
                status=(
                    DermanPost.Status.PUBLISHED
                ),
            )
        )

    def test_user_can_create_pending_derman(
        self,
    ):
        self.client.force_login(
            self.author
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Bu sorun için uyguladığım "
                    "çözüm adımlarını burada "
                    "detaylı şekilde paylaşıyorum."
                ),
                "confirm_no_edit": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "complaints:public_detail",
                args=[
                    self.complaint.pk
                ],
            ),
        )

        derman = (
            DermanPost.objects.get(
                complaint=self.complaint,
                author_user=self.author,
            )
        )

        self.assertEqual(
            derman.status,
            DermanPost.Status.PENDING,
        )

    def test_confirmation_is_required(
        self,
    ):
        self.client.force_login(
            self.author
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Bu metin yeterince uzun "
                    "ancak confirmation "
                    "işaretlenmemiştir."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            DermanPost.objects.filter(
                complaint=self.complaint,
                author_user=self.author,
            ).exists()
        )

    def test_complaint_owner_cannot_create_derman(
        self,
    ):
        self.client.force_login(
            self.owner
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Kendi şikayetime Derman "
                    "oluşturamam ve bu işlem "
                    "engellenmelidir."
                ),
                "confirm_no_edit": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            DermanPost.objects.filter(
                complaint=self.complaint,
                author_user=self.owner,
            ).exists()
        )

    def test_company_role_is_forbidden(
        self,
    ):
        self.client.force_login(
            self.company_user
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Şirket kullanıcısı Derman "
                    "oluşturamamalıdır."
                ),
                "confirm_no_edit": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_anonymous_user_redirected_to_login(
        self,
    ):
        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Anonymous kullanıcı "
                    "Derman gönderemez."
                ),
                "confirm_no_edit": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertIn(
            reverse("accounts:login"),
            response["Location"],
        )

    def test_create_endpoint_rejects_get(
        self,
    ):
        self.client.force_login(
            self.author
        )

        response = self.client.get(
            self.create_url()
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_author_can_withdraw_own_derman(
        self,
    ):
        derman = (
            self.create_published_derman()
        )

        self.client.force_login(
            self.author
        )

        response = self.client.post(
            self.withdraw_url(
                derman
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        derman.refresh_from_db()

        self.assertEqual(
            derman.status,
            DermanPost.Status.WITHDRAWN,
        )

        self.assertIsNotNone(
            derman.withdrawn_at,
        )

    def test_other_user_cannot_withdraw_derman(
        self,
    ):
        derman = (
            self.create_published_derman()
        )

        self.client.force_login(
            self.other
        )

        response = self.client.post(
            self.withdraw_url(
                derman
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        derman.refresh_from_db()

        self.assertEqual(
            derman.status,
            DermanPost.Status.PUBLISHED,
        )

    def test_reaction_create_switch_and_remove(
        self,
    ):
        derman = (
            self.create_published_derman()
        )

        self.client.force_login(
            self.other
        )

        url = self.reaction_url(
            derman
        )

        response = self.client.post(
            url,
            {
                "reaction_type":
                    DermanReaction.Type.LIKE,
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        reaction = (
            DermanReaction.objects.get(
                derman=derman,
                user=self.other,
            )
        )

        self.assertEqual(
            reaction.reaction_type,
            DermanReaction.Type.LIKE,
        )

        self.client.post(
            url,
            {
                "reaction_type":
                    DermanReaction.Type.DISLIKE,
            },
        )

        reaction.refresh_from_db()

        self.assertEqual(
            reaction.reaction_type,
            DermanReaction.Type.DISLIKE,
        )

        self.client.post(
            url,
            {
                "reaction_type":
                    DermanReaction.Type.DISLIKE,
            },
        )

        self.assertFalse(
            DermanReaction.objects.filter(
                derman=derman,
                user=self.other,
            ).exists()
        )

    def test_author_cannot_react_to_own_derman(
        self,
    ):
        derman = (
            self.create_published_derman()
        )

        self.client.force_login(
            self.author
        )

        response = self.client.post(
            self.reaction_url(
                derman
            ),
            {
                "reaction_type":
                    DermanReaction.Type.LIKE,
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_url_complaint_mismatch_returns_404(
        self,
    ):
        derman = (
            self.create_published_derman()
        )

        second_complaint = (
            Complaint.objects.create(
                user=self.owner,
                company=self.company,
                title=(
                    "Başka şikayet"
                ),
                description=(
                    "Başka bir şikayet için "
                    "yeterince uzun açıklama."
                ),
                status=(
                    Complaint.Status.PUBLISHED
                ),
            )
        )

        self.client.force_login(
            self.other
        )

        response = self.client.post(
            self.reaction_url(
                derman,
                complaint=(
                    second_complaint
                ),
            ),
            {
                "reaction_type":
                    DermanReaction.Type.LIKE,
            },
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_create_requires_csrf(
        self,
    ):
        csrf_client = Client(
            enforce_csrf_checks=True
        )

        csrf_client.force_login(
            self.author
        )

        response = csrf_client.post(
            self.create_url(),
            {
                "body": (
                    "CSRF olmadan bu Derman "
                    "oluşturma işlemi başarılı "
                    "olmamalıdır."
                ),
                "confirm_no_edit": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            DermanPost.objects.filter(
                complaint=self.complaint,
                author_user=self.author,
            ).exists()
        )