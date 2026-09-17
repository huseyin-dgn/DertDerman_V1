from dataclasses import dataclass
from enum import Enum

from accounts.models import User
from companies.models import CompanyMembership
from companies.services import active_company_memberships_for


class ActorKind(str, Enum):
    ANONYMOUS = "ANONYMOUS"
    USER = "USER"
    COMPANY = "COMPANY"
    ADMIN = "ADMIN"
    INVALID = "INVALID"


@dataclass(frozen=True)
class AssistantContext:
    kind: ActorKind
    user: object | None = None
    company_memberships: tuple[CompanyMembership, ...] = ()


def resolve_actor_context(user) -> AssistantContext:
    if user is None or not getattr(user, "is_authenticated", False):
        return AssistantContext(kind=ActorKind.ANONYMOUS)

    if (
        not getattr(user, "pk", None)
        or not getattr(user, "is_active", False)
        or getattr(user, "is_permanently_closed", False)
    ):
        return AssistantContext(
            kind=ActorKind.INVALID,
            user=user,
        )

    user_type = getattr(user, "user_type", None)

    if user_type == User.UserType.USER:
        return AssistantContext(
            kind=ActorKind.USER,
            user=user,
        )

    if user_type == User.UserType.COMPANY:
        memberships = tuple(
            active_company_memberships_for(user)
        )
        if not memberships:
            return AssistantContext(
                kind=ActorKind.INVALID,
                user=user,
            )

        return AssistantContext(
            kind=ActorKind.COMPANY,
            user=user,
            company_memberships=memberships,
        )

    if user_type == User.UserType.ADMIN:
        return AssistantContext(
            kind=ActorKind.ADMIN,
            user=user,
        )

    return AssistantContext(
        kind=ActorKind.INVALID,
        user=user,
    )


def resolve_company_membership(
    context: AssistantContext,
    company_id,
) -> CompanyMembership | None:
    if context.kind != ActorKind.COMPANY:
        return None

    if isinstance(company_id, bool) or not isinstance(company_id, int):
        return None

    if company_id <= 0:
        return None

    for membership in context.company_memberships:
        if membership.company_id == company_id:
            return membership

    return None
