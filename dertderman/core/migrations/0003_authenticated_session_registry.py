from datetime import (
    datetime,
    timezone as dt_timezone,
)

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.core import signing
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def _timestamp_or_default(value, default):
    try:
        value = int(value)
        if value <= 0:
            return default

        return datetime.fromtimestamp(
            value,
            tz=dt_timezone.utc,
        )
    except (
        TypeError,
        ValueError,
        OSError,
        OverflowError,
    ):
        return default


def backfill_authenticated_sessions(
    apps,
    schema_editor,
):
    Session = apps.get_model(
        "sessions",
        "Session",
    )

    User = apps.get_model(
        "accounts",
        "User",
    )

    AuthenticatedSession = apps.get_model(
        "core",
        "AuthenticatedSession",
    )

    now = django.utils.timezone.now()
    store = SessionStore()

    sessions = (
        Session.objects
        .filter(expire_date__gt=now)
        .iterator(chunk_size=500)
    )

    for session in sessions:
        try:
            decoded = signing.loads(
                session.session_data,
                salt=store.key_salt,
                serializer=store.serializer,
            )
        except Exception:
            # Unverifiable persisted session data is not trusted.
            session.delete()
            continue

        auth_user_id = decoded.get(
            "_auth_user_id"
        )

        if auth_user_id is None:
            # Valid anonymous session.
            continue

        try:
            user_id = int(auth_user_id)
        except (TypeError, ValueError):
            session.delete()
            continue

        user = (
            User.objects
            .filter(pk=user_id)
            .only(
                "pk",
                "user_type",
            )
            .first()
        )

        if user is None:
            session.delete()
            continue

        role = (
            user.user_type
            or ""
        ).strip().upper()

        if role not in {
            "USER",
            "COMPANY",
            "ADMIN",
        }:
            session.delete()
            continue

        started_at = _timestamp_or_default(
            decoded.get(
                "_dd_auth_started_at"
            ),
            now,
        )

        last_seen_at = _timestamp_or_default(
            decoded.get(
                "_dd_auth_last_seen_at"
            ),
            started_at,
        )

        AuthenticatedSession.objects.get_or_create(
            session_id=session.session_key,
            defaults={
                "user_id": user_id,
                "role": role,
            },
        )

        # auto_now_add / auto_now create sırasında verilen
        # timestamp'leri ezebilir. QuerySet.update() field
        # pre_save davranışını bypass ederek gerçek eski session
        # zamanlarını korur.
        AuthenticatedSession.objects.filter(
            session_id=session.session_key
        ).update(
            user_id=user_id,
            role=role,
            created_at=started_at,
            last_seen_at=last_seen_at,
        )


def reverse_backfill(
    apps,
    schema_editor,
):
    AuthenticatedSession = apps.get_model(
        "core",
        "AuthenticatedSession",
    )

    AuthenticatedSession.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_iprisklog_abuseattempt"),
        ("sessions", "0001_initial"),
        migrations.swappable_dependency(
            settings.AUTH_USER_MODEL
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthenticatedSession",
            fields=[
                (
                    "session",
                    models.OneToOneField(
                        db_column="session_key",
                        on_delete=(
                            django.db.models.deletion.CASCADE
                        ),
                        primary_key=True,
                        related_name="+",
                        serialize=False,
                        to="sessions.session",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        max_length=20,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                    ),
                ),
                (
                    "last_seen_at",
                    models.DateTimeField(
                        auto_now=True,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=(
                            django.db.models.deletion.CASCADE
                        ),
                        related_name=(
                            "authenticated_sessions"
                        ),
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": (
                    "-last_seen_at",
                    "-created_at",
                ),
            },
        ),
        migrations.AddIndex(
            model_name="authenticatedsession",
            index=models.Index(
                fields=[
                    "user",
                    "created_at",
                ],
                name="authsess_user_created",
            ),
        ),
        migrations.AddIndex(
            model_name="authenticatedsession",
            index=models.Index(
                fields=[
                    "user",
                    "last_seen_at",
                ],
                name="authsess_user_seen",
            ),
        ),
        migrations.RunPython(
            backfill_authenticated_sessions,
            reverse_backfill,
        ),
    ]
