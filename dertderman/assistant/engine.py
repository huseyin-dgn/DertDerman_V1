from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from .actions import (
    ACTION_RULES,
    AssistantAction,
)
from .context import ActorKind, AssistantContext
from .permissions import action_allowed


@dataclass(frozen=True)
class EngineResponse:
    status_code: int
    payload: dict[str, object]


def _error(
    *,
    status_code: int,
    code: str,
    message: str,
) -> EngineResponse:
    return EngineResponse(
        status_code=status_code,
        payload={
            "ok": False,
            "error": code,
            "message": message,
        },
    )


def _denied_message(
    context: AssistantContext,
) -> str:
    if context.kind == ActorKind.ANONYMOUS:
        return (
            "Bu bilgiye erişmek için oturum açmanız gerekir."
        )

    return (
        "Bu işlem mevcut hesap bağlamında kullanılamaz."
    )


def run_action(
    *,
    context: AssistantContext,
    raw_action,
) -> EngineResponse:
    if not isinstance(raw_action, str):
        return _error(
            status_code=400,
            code="INVALID_ACTION",
            message="Geçersiz asistan işlemi.",
        )

    normalized_action = raw_action.strip()

    try:
        action = AssistantAction(normalized_action)
    except ValueError:
        return _error(
            status_code=400,
            code="UNKNOWN_ACTION",
            message="Bu asistan işlemi desteklenmiyor.",
        )

    rule = ACTION_RULES.get(action)
    if rule is None:
        return _error(
            status_code=400,
            code="UNKNOWN_ACTION",
            message="Bu asistan işlemi desteklenmiyor.",
        )

    if not action_allowed(
        context,
        allowed_actor_kinds=rule.allowed_actor_kinds,
        requires_private_user=rule.requires_private_user,
    ):
        return _error(
            status_code=403,
            code="ACCESS_DENIED",
            message=_denied_message(context),
        )

    try:
        reply = rule.handler(context)
    except PermissionDenied:
        return _error(
            status_code=403,
            code="ACCESS_DENIED",
            message=_denied_message(context),
        )

    return EngineResponse(
        status_code=200,
        payload={
            "ok": True,
            "action": action.value,
            "message": reply.message,
            "data": reply.data,
            "links": list(reply.links),
        },
    )
