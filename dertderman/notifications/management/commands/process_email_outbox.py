import logging
import signal
import threading
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.utils import timezone

from notifications.models import EmailOutbox
from notifications.outbox_service import (
    OutboxBusinessCancellation,
    OutboxClaimLost,
    OutboxConfigurationError,
    OutboxPermanentItemError,
    cancel_email_outbox_claim,
    claim_email_outbox,
    mark_email_outbox_permanent_failure,
    purge_cancelled_password_reset_noops,
    record_email_outbox_render_failure,
    release_email_outbox_claim,
    render_outbox_email,
    reset_email_outbox_render_failure_count,
    send_outbox_email,
    validate_worker_configuration,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process durable email outbox items."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--batch-size", type=int, default=25)
        parser.add_argument("--poll-seconds", type=float, default=2.0)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        poll_seconds = options["poll_seconds"]
        if batch_size < 1 or batch_size > 250:
            raise CommandError("--batch-size must be between 1 and 250.")
        if poll_seconds < 0.1 or poll_seconds > 300:
            raise CommandError("--poll-seconds must be between 0.1 and 300.")

        try:
            validate_worker_configuration()
        except OutboxConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        stop_event = threading.Event()

        def request_stop(_signum, _frame):
            stop_event.set()

        previous_handlers = {}
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                previous_handlers[signum] = signal.signal(signum, request_stop)
            except (ValueError, OSError):
                pass

        try:
            next_housekeeping_at = None
            while not stop_event.is_set():
                close_old_connections()
                now = timezone.now()
                if next_housekeeping_at is None or now >= next_housekeeping_at:
                    try:
                        purge_cancelled_password_reset_noops(now=now)
                    except Exception as exc:
                        logger.error(
                            "Email outbox housekeeping failed: exception_type=%s",
                            exc.__class__.__name__,
                        )
                    next_housekeeping_at = now + timedelta(hours=1)
                claims = claim_email_outbox(batch_size=batch_size)
                fatal_error = None
                processed_claims = 0

                for claim in claims:
                    if stop_event.is_set():
                        break
                    processed_claims += 1
                    try:
                        outbox = EmailOutbox.objects.get(pk=claim.outbox_id)
                        try:
                            payload = render_outbox_email(outbox)
                        except (
                            OutboxClaimLost,
                            EmailOutbox.DoesNotExist,
                            OutboxPermanentItemError,
                            OutboxBusinessCancellation,
                            OutboxConfigurationError,
                        ):
                            raise
                        except (TemplateDoesNotExist, TemplateSyntaxError):
                            raise OutboxConfigurationError(
                                "Required email templates are unavailable."
                            ) from None
                        except Exception as exc:
                            logger.error(
                                "Email outbox render failed unexpectedly: "
                                "outbox_id=%s kind=%s exception_type=%s",
                                claim.outbox_id,
                                outbox.kind,
                                exc.__class__.__name__,
                            )
                            try:
                                record_email_outbox_render_failure(
                                    outbox_id=claim.outbox_id,
                                    claim_token=claim.claim_token,
                                )
                            except OutboxClaimLost:
                                pass
                            continue

                        if outbox.render_failure_count > 0:
                            reset_email_outbox_render_failure_count(
                                outbox_id=claim.outbox_id,
                                claim_token=claim.claim_token,
                            )
                        send_outbox_email(
                            outbox_id=claim.outbox_id,
                            claim_token=claim.claim_token,
                            payload=payload,
                        )
                    except (OutboxClaimLost, EmailOutbox.DoesNotExist):
                        logger.info(
                            "Email outbox claim lost: outbox_id=%s",
                            claim.outbox_id,
                        )
                    except OutboxPermanentItemError as exc:
                        logger.warning(
                            "Email outbox item is permanently invalid: "
                            "outbox_id=%s kind=%s error_code=%s",
                            claim.outbox_id,
                            outbox.kind,
                            exc.code,
                        )
                        try:
                            mark_email_outbox_permanent_failure(
                                outbox_id=claim.outbox_id,
                                claim_token=claim.claim_token,
                                error_code=exc.code,
                            )
                        except OutboxClaimLost:
                            pass
                    except OutboxBusinessCancellation as exc:
                        try:
                            cancel_email_outbox_claim(
                                outbox_id=claim.outbox_id,
                                claim_token=claim.claim_token,
                                code=exc.code,
                            )
                        except OutboxClaimLost:
                            pass
                    except OutboxConfigurationError as exc:
                        fatal_error = exc
                        self._release_claim(claim, "WORKER_CONFIGURATION")
                        break
                    except Exception as exc:
                        logger.error(
                            "Email outbox dispatch failed unexpectedly: "
                            "outbox_id=%s exception_type=%s",
                            claim.outbox_id,
                            exc.__class__.__name__,
                        )
                        self._release_claim(claim, "WORKER_UNEXPECTED_ERROR")

                for claim in claims[processed_claims:]:
                    self._release_claim(claim, "WORKER_INTERRUPTED")

                if fatal_error is not None:
                    raise CommandError(str(fatal_error)) from fatal_error
                if options["once"]:
                    break
                if not claims:
                    stop_event.wait(poll_seconds)
        finally:
            close_old_connections()
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)

    @staticmethod
    def _release_claim(claim, code):
        try:
            release_email_outbox_claim(
                outbox_id=claim.outbox_id,
                claim_token=claim.claim_token,
                code=code,
            )
        except OutboxClaimLost:
            pass
