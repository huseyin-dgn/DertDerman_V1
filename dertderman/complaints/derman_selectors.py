from dataclasses import dataclass

from django.db.models import (
    CharField,
    Count,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
)

from accounts.models import User
from companies.plans import (
    company_has_active_pro,
)
from companies.services import (
    active_company_memberships_for,
)

from .models import (
    Complaint,
    DermanPost,
    DermanReaction,
)


class DermanAccessLevel:
    ANONYMOUS = "ANONYMOUS"
    USER = "USER"
    COMPANY_STANDARD = "COMPANY_STANDARD"
    COMPANY_PRO = "COMPANY_PRO"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class DermanVisibility:
    access_level: str

    published_count: int

    can_view_content: bool
    paywalled: bool

    can_create: bool
    can_react: bool

    dermans: object


def published_derman_count(
    complaint,
):
    return (
        DermanPost.objects
        .filter(
            complaint_id=complaint.pk,
            status=DermanPost.Status.PUBLISHED,
        )
        .count()
    )


def _empty_dermans():
    return (
        DermanPost.objects
        .none()
        .values(
            "id",
            "complaint_id",
            "author_user_id",
            "body",
            "created_at",
            "published_at",
        )
    )


def published_derman_cards(
    *,
    complaint,
    viewer=None,
):
    queryset = (
        DermanPost.objects
        .filter(
            complaint_id=complaint.pk,
            status=DermanPost.Status.PUBLISHED,
        )
        .annotate(
            author_username=F(
                "author_user__username"
            ),
            author_first_name=F(
                "author_user__first_name"
            ),
            author_selected_avatar=F(
                "author_user__selected_avatar"
            ),
            like_count=Count(
                "reactions",
                filter=Q(
                    reactions__reaction_type=(
                        DermanReaction.Type.LIKE
                    )
                ),
                distinct=True,
            ),
            dislike_count=Count(
                "reactions",
                filter=Q(
                    reactions__reaction_type=(
                        DermanReaction.Type.DISLIKE
                    )
                ),
                distinct=True,
            ),
        )
    )

    if (
        viewer is not None
        and getattr(
            viewer,
            "is_authenticated",
            False,
        )
        and getattr(
            viewer,
            "user_type",
            None,
        )
        == User.UserType.USER
        and getattr(
            viewer,
            "pk",
            None,
        )
    ):
        viewer_reaction = (
            DermanReaction.objects
            .filter(
                derman_id=OuterRef("pk"),
                user_id=viewer.pk,
            )
            .values(
                "reaction_type"
            )[:1]
        )

        queryset = (
            queryset.annotate(
                viewer_reaction=Subquery(
                    viewer_reaction,
                    output_field=CharField(),
                )
            )
        )

    else:
        queryset = (
            queryset.annotate(
                viewer_reaction=Value(
                    "",
                    output_field=CharField(),
                )
            )
        )

    return (
        queryset
        .values(
            "id",
            "complaint_id",
            "author_user_id",
            "body",
            "created_at",
            "published_at",
            "author_username",
            "author_first_name",
            "author_selected_avatar",
            "like_count",
            "dislike_count",
            "viewer_reaction",
        )
        .order_by(
            "-published_at",
            "-id",
        )
    )


def _user_can_create_derman(
    *,
    user,
    complaint,
):
    if (
        complaint.status
        != Complaint.Status.PUBLISHED
    ):
        return False

    if (
        complaint.user_id
        == user.pk
    ):
        return False

    already_exists = (
        DermanPost.objects
        .filter(
            complaint_id=complaint.pk,
            author_user_id=user.pk,
        )
        .exists()
    )

    return not already_exists


def derman_visibility_for(
    *,
    user,
    complaint,
):
    count = published_derman_count(
        complaint
    )

    authenticated = bool(
        user
        and getattr(
            user,
            "is_authenticated",
            False,
        )
    )

    if not authenticated:
        return DermanVisibility(
            access_level=(
                DermanAccessLevel.ANONYMOUS
            ),
            published_count=count,
            can_view_content=False,
            paywalled=False,
            can_create=False,
            can_react=False,
            dermans=_empty_dermans(),
        )

    role = getattr(
        user,
        "user_type",
        None,
    )

    if role == User.UserType.USER:
        return DermanVisibility(
            access_level=(
                DermanAccessLevel.USER
            ),
            published_count=count,
            can_view_content=True,
            paywalled=False,
            can_create=(
                _user_can_create_derman(
                    user=user,
                    complaint=complaint,
                )
            ),
            can_react=(
                complaint.status
                == Complaint.Status.PUBLISHED
            ),
            dermans=(
                published_derman_cards(
                    complaint=complaint,
                    viewer=user,
                )
            ),
        )

    if (
        role == User.UserType.ADMIN
        and getattr(
            user,
            "is_active",
            False,
        )
        and not getattr(
            user,
            "is_permanently_closed",
            False,
        )
    ):
        return DermanVisibility(
            access_level=(
                DermanAccessLevel.ADMIN
            ),
            published_count=count,
            can_view_content=True,
            paywalled=False,
            can_create=False,
            can_react=False,
            dermans=(
                published_derman_cards(
                    complaint=complaint,
                )
            ),
        )

    if role == User.UserType.COMPANY:
        membership_exists = (
            active_company_memberships_for(
                user
            )
            .filter(
                company_id=(
                    complaint.company_id
                )
            )
            .exists()
        )

        has_pro_access = (
            membership_exists
            and company_has_active_pro(
                complaint.company
            )
        )

        if has_pro_access:
            return DermanVisibility(
                access_level=(
                    DermanAccessLevel.COMPANY_PRO
                ),
                published_count=count,
                can_view_content=True,
                paywalled=False,
                can_create=False,
                can_react=False,
                dermans=(
                    published_derman_cards(
                        complaint=complaint,
                    )
                ),
            )

        return DermanVisibility(
            access_level=(
                DermanAccessLevel.COMPANY_STANDARD
            ),
            published_count=count,
            can_view_content=False,
            paywalled=(count > 0),
            can_create=False,
            can_react=False,
            dermans=_empty_dermans(),
        )

    return DermanVisibility(
        access_level=(
            DermanAccessLevel.ANONYMOUS
        ),
        published_count=count,
        can_view_content=False,
        paywalled=False,
        can_create=False,
        can_react=False,
        dermans=_empty_dermans(),
    )