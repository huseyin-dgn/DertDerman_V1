from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from companies.models import Company

from .derman_services import (
    DermanAlreadyExists,
    DermanRateLimited,
    DermanStateConflict,
    create_derman,
    toggle_derman_reaction,
    withdraw_derman,
)
from .models import (
    Complaint,
    DermanPost,
    DermanReaction,
)


User = get_user_model()


class DermanServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.complaint_owner = User.objects.create_user(
            username="derman-complaint-owner",
            email="derman-owner@example.com",
            user_type=User.UserType.USER,
        )

        cls.derman_user = User.objects.create_user(
            username="derman-user",
            email="derman-user@example.com",
            user_type=User.UserType.USER,
        )

        cls.other_user = User.objects.create_user(
            username="derman-other",
            email="derman-other@example.com",
            user_type=User.UserType.USER,
        )

        cls.company_user = User.objects.create_user(
            username="derman-company-user",
            email="derman-company@example.com",
            user_type=User.UserType.COMPANY,
        )

        cls.company = Company.objects.create(
            name="Derman Test Company",
        )

    def create_complaint(
        self,
        *,
        owner=None,
        status=Complaint.Status.PUBLISHED,
        title="Derman test complaint",
    ):
        return Complaint.objects.create(
            user=owner or self.complaint_owner,
            company=self.company,
            title=title,
            description=(
                "Bu açıklama Derman Ol servis testleri "
                "için yeterince uzun bir açıklamadır."
            ),
            status=status,
        )

    def test_user_can_create_pending_derman(self):
        complaint = self.create_complaint()

        derman = create_derman(
            complaint_id=complaint.pk,
            actor=self.derman_user,
            body=(
                "Benzer bir sorun yaşamıştım ve "
                "şu yöntemle çözüm sağlamıştım."
            ),
        )

        self.assertEqual(
            derman.status,
            DermanPost.Status.PENDING,
        )
        self.assertEqual(
            derman.complaint_id,
            complaint.pk,
        )
        self.assertEqual(
            derman.author_user_id,
            self.derman_user.pk,
        )

    def test_user_cannot_derman_own_complaint(self):
        complaint = self.create_complaint(
            owner=self.derman_user,
        )

        with self.assertRaises(PermissionDenied):
            create_derman(
                complaint_id=complaint.pk,
                actor=self.derman_user,
                body=(
                    "Kendi şikayetime Derman Ol "
                    "paylaşımı yapamam."
                ),
            )

    def test_company_user_cannot_create_derman(self):
        complaint = self.create_complaint()

        with self.assertRaises(PermissionDenied):
            create_derman(
                complaint_id=complaint.pk,
                actor=self.company_user,
                body=(
                    "Şirket hesabı Derman Ol "
                    "oluşturamamalıdır."
                ),
            )

    def test_derman_can_only_be_created_on_published_complaint(self):
        resolved = self.create_complaint(
            status=Complaint.Status.RESOLVED,
            title="Resolved complaint",
        )

        pending = self.create_complaint(
            status=Complaint.Status.PENDING,
            title="Pending complaint",
        )

        for complaint in (
            resolved,
            pending,
        ):
            with self.subTest(
                status=complaint.status
            ):
                with self.assertRaises(
                    DermanStateConflict
                ):
                    create_derman(
                        complaint_id=complaint.pk,
                        actor=self.derman_user,
                        body=(
                            "Bu şikayet uygun durumda "
                            "olmadığı için oluşmamalıdır."
                        ),
                    )

    def test_withdraw_does_not_restore_creation_right(self):
        complaint = self.create_complaint()

        derman = create_derman(
            complaint_id=complaint.pk,
            actor=self.derman_user,
            body=(
                "Bu Derman daha sonra kullanıcı "
                "tarafından geri çekilecektir."
            ),
        )

        withdrawn = withdraw_derman(
            derman_id=derman.pk,
            actor=self.derman_user,
        )

        self.assertEqual(
            withdrawn.status,
            DermanPost.Status.WITHDRAWN,
        )
        self.assertIsNotNone(
            withdrawn.withdrawn_at,
        )

        with self.assertRaises(
            DermanAlreadyExists
        ):
            create_derman(
                complaint_id=complaint.pk,
                actor=self.derman_user,
                body=(
                    "Geri çekmeden sonra ikinci "
                    "Derman oluşturulamamalıdır."
                ),
            )

    def test_other_user_cannot_withdraw_derman(self):
        complaint = self.create_complaint()

        derman = create_derman(
            complaint_id=complaint.pk,
            actor=self.derman_user,
            body=(
                "Bu Derman sadece kendi yazarı "
                "tarafından geri çekilebilir."
            ),
        )

        with self.assertRaises(PermissionDenied):
            withdraw_derman(
                derman_id=derman.pk,
                actor=self.other_user,
            )

    def test_rejected_derman_cannot_be_withdrawn(self):
        complaint = self.create_complaint()

        derman = DermanPost.objects.create(
            complaint=complaint,
            author_user=self.derman_user,
            body=(
                "Bu Derman moderasyon tarafından "
                "reddedilmiş kabul edilmektedir."
            ),
            status=DermanPost.Status.REJECTED,
        )

        with self.assertRaises(
            DermanStateConflict
        ):
            withdraw_derman(
                derman_id=derman.pk,
                actor=self.derman_user,
            )

    def test_reaction_create_switch_and_toggle_off(self):
        complaint = self.create_complaint()

        derman = DermanPost.objects.create(
            complaint=complaint,
            author_user=self.derman_user,
            body=(
                "Bu yayınlanmış Derman reaction "
                "işlemlerini test etmek içindir."
            ),
            status=DermanPost.Status.PUBLISHED,
        )

        created = toggle_derman_reaction(
            derman_id=derman.pk,
            actor=self.other_user,
            reaction_type=DermanReaction.Type.LIKE,
        )

        self.assertEqual(
            created.action,
            "CREATED",
        )

        reaction = DermanReaction.objects.get(
            derman=derman,
            user=self.other_user,
        )

        self.assertEqual(
            reaction.reaction_type,
            DermanReaction.Type.LIKE,
        )

        updated = toggle_derman_reaction(
            derman_id=derman.pk,
            actor=self.other_user,
            reaction_type=DermanReaction.Type.DISLIKE,
        )

        self.assertEqual(
            updated.action,
            "UPDATED",
        )

        reaction.refresh_from_db()

        self.assertEqual(
            reaction.reaction_type,
            DermanReaction.Type.DISLIKE,
        )

        removed = toggle_derman_reaction(
            derman_id=derman.pk,
            actor=self.other_user,
            reaction_type=DermanReaction.Type.DISLIKE,
        )

        self.assertEqual(
            removed.action,
            "REMOVED",
        )

        self.assertFalse(
            DermanReaction.objects.filter(
                derman=derman,
                user=self.other_user,
            ).exists()
        )

    def test_author_cannot_react_to_own_derman(self):
        complaint = self.create_complaint()

        derman = DermanPost.objects.create(
            complaint=complaint,
            author_user=self.derman_user,
            body=(
                "Derman yazarı kendi içeriğine "
                "tepki verememelidir."
            ),
            status=DermanPost.Status.PUBLISHED,
        )

        with self.assertRaises(PermissionDenied):
            toggle_derman_reaction(
                derman_id=derman.pk,
                actor=self.derman_user,
                reaction_type=DermanReaction.Type.LIKE,
            )

    def test_reaction_blocked_after_parent_is_resolved(self):
        complaint = self.create_complaint()

        derman = DermanPost.objects.create(
            complaint=complaint,
            author_user=self.derman_user,
            body=(
                "Parent complaint çözüldükten sonra "
                "yeni reaction yapılamamalıdır."
            ),
            status=DermanPost.Status.PUBLISHED,
        )

        complaint.status = (
            Complaint.Status.RESOLVED
        )
        complaint.save(
            update_fields=("status",)
        )

        with self.assertRaises(
            DermanStateConflict
        ):
            toggle_derman_reaction(
                derman_id=derman.pk,
                actor=self.other_user,
                reaction_type=DermanReaction.Type.LIKE,
            )

    def test_create_rate_limit_is_ten_per_24_hours(self):
        for index in range(10):
            complaint = self.create_complaint(
                title=f"Rate limit complaint {index}",
            )

            DermanPost.objects.create(
                complaint=complaint,
                author_user=self.derman_user,
                body=(
                    f"Rate limit için oluşturulan "
                    f"Derman paylaşımı {index} yeterli "
                    f"uzunluğa sahiptir."
                ),
                status=DermanPost.Status.PENDING,
            )

        target = self.create_complaint(
            title="Rate limit target",
        )

        with self.assertRaises(
            DermanRateLimited
        ):
            create_derman(
                complaint_id=target.pk,
                actor=self.derman_user,
                body=(
                    "On birinci Derman paylaşımı "
                    "24 saatlik limite takılmalıdır."
                ),
            )