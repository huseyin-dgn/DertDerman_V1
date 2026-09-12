from __future__ import annotations

from django.db.models import F


MAX_TRACKED_OBJECTS_PER_TYPE = 500


def record_unique_session_view(
    request,
    *,
    instance,
    namespace: str,
) -> int:
    if request.method != "GET":
        return int(
            getattr(
                instance,
                "view_count",
                0,
            )
            or 0
        )

    session_key = f"_dd_viewed_{namespace}"

    viewed = list(
        request.session.get(
            session_key,
            [],
        )
    )

    object_key = str(instance.pk)

    if object_key in viewed:
        return int(instance.view_count or 0)

    instance.__class__.objects.filter(
        pk=instance.pk
    ).update(
        view_count=F("view_count") + 1
    )

    instance.view_count = (
        int(instance.view_count or 0)
        + 1
    )

    viewed.append(object_key)

    request.session[session_key] = viewed[
        -MAX_TRACKED_OBJECTS_PER_TYPE:
    ]

    request.session.modified = True

    return int(instance.view_count)
