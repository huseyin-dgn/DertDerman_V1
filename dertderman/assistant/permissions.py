from accounts.models import User

from .context import ActorKind, AssistantContext


def is_valid_private_user(user) -> bool:
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "pk", None)
        and getattr(user, "user_type", None) == User.UserType.USER
        and getattr(user, "is_active", False)
        and not getattr(user, "is_permanently_closed", False)
        and getattr(user, "is_verified", False)
    )


def action_allowed(
    context: AssistantContext,
    *,
    allowed_actor_kinds: frozenset[ActorKind],
    requires_private_user: bool = False,
) -> bool:
    if context.kind not in allowed_actor_kinds:
        return False

    if requires_private_user and not is_valid_private_user(context.user):
        return False

    return True
