import json
from json import JSONDecodeError

from django.http import JsonResponse
from django.utils.cache import patch_vary_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from core.rate_limit import (
    client_ip,
    consume_rate_limit,
)

from .context import resolve_actor_context
from .engine import run_action


MAX_REQUEST_BODY_BYTES = 2048
MAX_ACTION_LENGTH = 64

ANONYMOUS_RATE_LIMIT = 30
AUTHENTICATED_RATE_LIMIT = 60
RATE_LIMIT_WINDOW_SECONDS = 60


class AssistantRequestError(ValueError):
    def __init__(
        self,
        message,
        *,
        status_code=400,
        code="INVALID_REQUEST",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _json_response(
    payload,
    *,
    status=200,
):
    response = JsonResponse(
        payload,
        status=status,
        json_dumps_params={
            "ensure_ascii": False,
        },
    )

    # Assistant responses can contain authenticated user data.
    # Keep them out of browser/shared caches and make Cookie part
    # of the cache variation contract.
    response["Cache-Control"] = (
        "private, no-store, no-cache, "
        "max-age=0, must-revalidate"
    )
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"

    # Conservative response hardening for the JSON endpoint.
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["X-Frame-Options"] = "DENY"

    patch_vary_headers(
        response,
        ("Cookie",),
    )

    return response


def _load_action(
    request,
):
    if request.content_type != "application/json":
        raise AssistantRequestError(
            "Asistan isteği JSON olmalıdır.",
            status_code=415,
            code="UNSUPPORTED_MEDIA_TYPE",
        )

    raw_body = request.body

    if not raw_body:
        raise AssistantRequestError(
            "Asistan isteği boş olamaz."
        )

    if len(raw_body) > MAX_REQUEST_BODY_BYTES:
        raise AssistantRequestError(
            "Asistan isteği çok büyük.",
            status_code=413,
            code="REQUEST_TOO_LARGE",
        )

    try:
        decoded = raw_body.decode(
            "utf-8"
        )
        payload = json.loads(
            decoded
        )

    except (
        UnicodeDecodeError,
        JSONDecodeError,
    ):
        raise AssistantRequestError(
            "Geçersiz JSON isteği."
        ) from None

    if not isinstance(
        payload,
        dict,
    ):
        raise AssistantRequestError(
            "Asistan isteği nesne olmalıdır."
        )

    # Button-only assistant:
    # never accept user/company/complaint ids or arbitrary text.
    if set(payload) != {
        "action",
    }:
        raise AssistantRequestError(
            "Asistan isteğinde desteklenmeyen alan var."
        )

    action = payload.get(
        "action"
    )

    if not isinstance(
        action,
        str,
    ):
        raise AssistantRequestError(
            "Asistan action alanı metin olmalıdır."
        )

    action = action.strip()

    if (
        not action
        or len(action) > MAX_ACTION_LENGTH
    ):
        raise AssistantRequestError(
            "Geçersiz asistan action değeri."
        )

    return action


def _consume_assistant_rate_limit(
    request,
):
    user = getattr(
        request,
        "user",
        None,
    )

    if (
        user is not None
        and getattr(
            user,
            "is_authenticated",
            False,
        )
        and getattr(
            user,
            "pk",
            None,
        )
    ):
        return consume_rate_limit(
            scope="assistant-auth-user",
            identifier=user.pk,
            limit=AUTHENTICATED_RATE_LIMIT,
            window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        )

    return consume_rate_limit(
        scope="assistant-anon-ip",
        identifier=client_ip(
            request
        ),
        limit=ANONYMOUS_RATE_LIMIT,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )


@never_cache
@require_POST
def interact(
    request,
):
    rate_limit = (
        _consume_assistant_rate_limit(
            request
        )
    )

    if not rate_limit.allowed:
        response = _json_response(
            {
                "ok": False,
                "error": "RATE_LIMITED",
                "message": (
                    "Çok fazla asistan isteği gönderildi. "
                    "Lütfen kısa bir süre sonra tekrar deneyin."
                ),
            },
            status=429,
        )

        response["Retry-After"] = str(
            rate_limit.retry_after
        )

        return response

    try:
        action = _load_action(
            request
        )

    except AssistantRequestError as error:
        return _json_response(
            {
                "ok": False,
                "error": error.code,
                "message": str(
                    error
                ),
            },
            status=error.status_code,
        )

    context = resolve_actor_context(
        request.user
    )

    result = run_action(
        context=context,
        raw_action=action,
    )

    return _json_response(
        result.payload,
        status=result.status_code,
    )
