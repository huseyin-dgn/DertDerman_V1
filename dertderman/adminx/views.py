from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from accounts.models import User
from blog.models import Post
from companies.models import Company, CompanyNotification
from complaints.models import Complaint, ContentReport, UserViolation
from core.models import ContactRequest
from core.pagination import PREVIEW_SIZE, paginate
from notifications.selectors import inbox
from notifications.services import mark_read

from .decorators import admin_required
from .filters import ComplaintFilters, EventFilters, list_context
from .forms import ContactStatusForm
from .models import AdminAuditLog
from .services import record_admin_audit


@admin_required
@require_safe
def home(request):
    pending_count = Complaint.objects.filter(
        status=Complaint.Status.PENDING
    ).count()

    pending_company_count = Company.objects.filter(
        approval_status=Company.ApprovalStatus.PENDING
    ).count()

    counts = Complaint.objects.aggregate(
        published=Count(
            "pk",
            filter=Q(status=Complaint.Status.PUBLISHED),
        ),
        resolved=Count(
            "pk",
            filter=Q(status=Complaint.Status.RESOLVED),
        ),
    )

    return render(
        request,
        "adminx/home.html",
        {
            "pending_count": pending_count,
            "recent_notifications": inbox(
                request.user,
                "ADMIN",
            )[:PREVIEW_SIZE],
            "pending_company_count": pending_company_count,
            "user_count": User.objects.count(),
            "company_count": Company.objects.count(),
            "published_count": counts["published"],
            "resolved_count": counts["resolved"],
            "blog_count": Post.objects.filter(
                status=Post.Status.PUBLISHED
            ).count(),
            "activity_count": CompanyNotification.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=7)
            ).count(),
            "recent_complaints": _moderation_complaints().order_by(
                "-created_at",
                "-pk",
            )[:PREVIEW_SIZE],
            "recent_applications": Company.objects.filter(
                approval_status=Company.ApprovalStatus.PENDING
            ).order_by(
                "-created_at",
                "-pk",
            )[:PREVIEW_SIZE],
            "recent_users": User.objects.only(
                "username",
                "first_name",
                "last_name",
                "date_joined",
                "user_type",
            ).order_by(
                "-date_joined",
                "-pk",
            )[:PREVIEW_SIZE],
            "recent_posts": Post.objects.filter(
                status=Post.Status.PUBLISHED
            ).defer(
                "content"
            ).order_by(
                "-published_at",
                "-pk",
            )[:PREVIEW_SIZE],
        },
    )


def _moderation_complaints():
    return Complaint.objects.select_related(
        "company",
        "user",
    ).only(
        "company__name",
        "user__username",
        "title",
        "description",
        "status",
        "created_at",
        "updated_at",
    )


@admin_required
@require_safe
def complaint_list(request):
    context = list_context(
        request,
        _moderation_complaints(),
        ComplaintFilters,
        search_fields=(
            "title",
            "user__username",
            "company__name",
        ),
        fields={
            "status": "status",
            "company": "company",
        },
        defaults={
            "status": Complaint.Status.PENDING,
        },
    )

    context["complaints"] = context["page_obj"]

    return render(
        request,
        "adminx/complaint_list.html",
        context,
    )


@admin_required
@require_safe
def notifications(request):
    return render(
        request,
        "notifications/admin_list.html",
        {
            "page_obj": paginate(
                request,
                inbox(request.user, "ADMIN"),
                "admin_notifications",
            )
        },
    )


@admin_required
@require_POST
def notification_read(request, pk):
    notification = get_object_or_404(
        inbox(request.user, "ADMIN"),
        pk=pk,
    )

    mark_read(
        inbox(request.user, "ADMIN").filter(
            pk=notification.pk,
        )
    )

    return redirect("adminx:notifications")


@admin_required
@require_safe
def notification_open(request, pk):
    notification = get_object_or_404(
        inbox(request.user, "ADMIN"),
        pk=pk,
    )

    return redirect(notification.target_url)


@admin_required
@require_POST
def notifications_read_all(request):
    mark_read(
        inbox(
            request.user,
            "ADMIN",
        )
    )

    return redirect("adminx:notifications")


@admin_required
@require_safe
def activity(request):
    return _event_list(
        request,
        "activity",
    )


@admin_required
@require_safe
def contact_list(request):
    queryset = ContactRequest.objects.all()

    status = request.GET.get(
        "status",
        "",
    )

    if status in ContactRequest.Status.values:
        queryset = queryset.filter(
            status=status,
        )

    return render(
        request,
        "adminx/contact_list.html",
        {
            "page_obj": paginate(
                request,
                queryset,
                "admin",
            ),
            "active_status": status,
            "status_options": ContactRequest.Status.choices,
        },
    )


@admin_required
@require_safe
def contact_detail(request, pk):
    item = get_object_or_404(
        ContactRequest,
        pk=pk,
    )

    return render(
        request,
        "adminx/contact_detail.html",
        {
            "contact_request": item,
            "form": ContactStatusForm(
                initial={
                    "status": item.status,
                }
            ),
        },
    )


@admin_required
@require_POST
def contact_status(request, pk):
    item = get_object_or_404(
        ContactRequest,
        pk=pk,
    )

    old_status = item.status

    form = ContactStatusForm(
        request.POST,
    )

    if form.is_valid():
        item.status = form.cleaned_data["status"]

        item.save(
            update_fields=("status",),
        )

        record_admin_audit(
            actor=request.user,
            action=AdminAuditLog.Action.UPDATE,
            target_type="contact_request",
            target_id=item.pk,
            target_label=f"İletişim talebi #{item.pk}",
            description="İletişim talebi durumu güncellendi.",
            metadata={
                "previous_status": old_status,
                "new_status": item.status,
            },
            request=request,
        )

        messages.success(
            request,
            "İletişim talebi durumu güncellendi.",
        )

    else:
        messages.error(
            request,
            "Geçerli bir durum seçin.",
        )

    return redirect(
        "adminx:contact_detail",
        pk=item.pk,
    )


def _event_list(request, kind):
    context = list_context(
        request,
        CompanyNotification.objects.select_related(
            "company",
            "complaint",
        ),
        EventFilters,
        search_fields=(
            "title",
            "company__name",
        ),
        fields={
            "kind": "kind",
        },
    )

    context["is_activity"] = (
        kind == "activity"
    )

    return render(
        request,
        "adminx/event_list.html",
        context,
    )


@admin_required
@require_safe
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        _moderation_complaints(),
        pk=pk,
    )

    return render(
        request,
        "adminx/complaint_detail.html",
        {
            "complaint": complaint,
        },
    )


@transaction.atomic
def _moderate(request, pk, target_status):
    complaint_before = get_object_or_404(
        Complaint.objects.only(
            "pk",
            "title",
            "status",
        ),
        pk=pk,
    )

    previous_status = complaint_before.status

    changed = Complaint.objects.filter(
        pk=pk,
        status=Complaint.Status.PENDING,
    ).update(
        status=target_status,
        updated_at=timezone.now(),
    )

    if not changed:
        complaint = get_object_or_404(
            _moderation_complaints(),
            pk=pk,
        )

        return render(
            request,
            "adminx/complaint_detail.html",
            {
                "complaint": complaint,
                "moderation_error": (
                    "Bu şikayet artık incelemede değil. "
                    "Karar uygulanmadı."
                ),
            },
            status=409,
        )

    from companies.panel_events import (
        record_complaint_notification,
    )
    from complaints.events import record_event
    from complaints.models import ComplaintEvent

    complaint = Complaint.objects.get(
        pk=pk,
    )

    event_type = (
        ComplaintEvent.Type.PUBLISHED
        if target_status == Complaint.Status.PUBLISHED
        else ComplaintEvent.Type.REJECTED
    )

    record_event(
        complaint,
        event_type,
        actor_type=ComplaintEvent.Actor.ADMIN,
        source_key=(
            f"complaint:{pk}:moderation:{target_status}"
        ),
        occurred_at=complaint.updated_at,
    )

    record_complaint_notification(
        complaint,
        (
            CompanyNotification.Kind.PUBLISHED
            if target_status == Complaint.Status.PUBLISHED
            else CompanyNotification.Kind.ADMIN
        ),
    )

    audit_action = (
        AdminAuditLog.Action.PUBLISH
        if target_status == Complaint.Status.PUBLISHED
        else AdminAuditLog.Action.REJECT
    )

    record_admin_audit(
        actor=request.user,
        action=audit_action,
        target_type="complaint",
        target_id=complaint.pk,
        target_label=complaint.title,
        description=(
            "Şikayet yayınlandı."
            if target_status == Complaint.Status.PUBLISHED
            else "Şikayet reddedildi."
        ),
        metadata={
            "previous_status": previous_status,
            "new_status": target_status,
        },
        request=request,
    )

    messages.success(
        request,
        (
            "Şikayet yayınlandı."
            if target_status == Complaint.Status.PUBLISHED
            else "Şikayet reddedildi."
        ),
    )

    return redirect(
        "adminx:complaint_detail",
        pk=pk,
    )


@admin_required
@require_POST
def complaint_publish(request, pk):
    return _moderate(
        request,
        pk,
        Complaint.Status.PUBLISHED,
    )


@admin_required
@require_POST
def complaint_reject(request, pk):
    return _moderate(
        request,
        pk,
        Complaint.Status.REJECTED,
    )


@admin_required
@require_POST
def complaint_resolve(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.only(
            "pk",
            "title",
            "status",
        ),
        pk=pk,
    )

    previous_status = complaint.status

    from complaints.services import (
        ComplaintStateConflict,
        resolve_complaint,
    )

    try:
        resolve_complaint(
            complaint_id=pk,
            actor=request.user,
        )

    except ComplaintStateConflict:
        messages.warning(
            request,
            (
                "Yalnızca yayındaki bir şikayet "
                "çözüldü olarak işaretlenebilir."
            ),
        )

    else:
        record_admin_audit(
            actor=request.user,
            action=AdminAuditLog.Action.RESOLVE,
            target_type="complaint",
            target_id=complaint.pk,
            target_label=complaint.title,
            description=(
                "Şikayet çözüldü olarak işaretlendi."
            ),
            metadata={
                "previous_status": previous_status,
                "new_status": Complaint.Status.RESOLVED,
            },
            request=request,
        )

        messages.success(
            request,
            "Şikayet çözüldü olarak işaretlendi.",
        )

    return redirect(
        "adminx:complaint_detail",
        pk=pk,
    )

@admin_required
@require_safe
def audit_log_list(request):
    queryset = AdminAuditLog.objects.select_related(
        "actor",
    ).all()

    page_obj = paginate(
        request,
        queryset,
        "admin",
    )

    return render(
        request,
        "adminx/audit_log_list.html",
        {
            "page_obj": page_obj,
        },
    )

@admin_required
@require_safe
def report_list(request):
    reports = (
        ContentReport.objects
        .select_related(
            "reporter",
            "complaint",
            "comment",
            "comment__author_user",
            "reviewed_by",
        )
        .all()
    )

    active_status = request.GET.get("status", "PENDING")

    if active_status in ContentReport.Status.values:
        reports = reports.filter(status=active_status)
    elif active_status != "all":
        active_status = "PENDING"
        reports = reports.filter(status=ContentReport.Status.PENDING)

    search = request.GET.get("q", "").strip()[:100]

    if search:
        reports = reports.filter(
            Q(reporter__username__icontains=search)
            | Q(complaint__title__icontains=search)
            | Q(comment__body__icontains=search)
            | Q(description__icontains=search)
        )

    reports = reports.order_by(
        "-created_at",
        "-pk",
    )

    page_obj = paginate(
        request,
        reports,
        "admin",
    )

    return render(
        request,
        "adminx/report_list.html",
        {
            "page_obj": page_obj,
            "active_status": active_status,
            "search": search,
            "status_options": ContentReport.Status.choices,
        },
    )


@admin_required
@require_safe
def report_detail(request, pk):
    report = get_object_or_404(
        ContentReport.objects.select_related(
            "reporter",
            "complaint",
            "complaint__user",
            "complaint__company",
            "comment",
            "comment__author_user",
            "reviewed_by",
        ),
        pk=pk,
    )

    return render(
        request,
        "adminx/report_detail.html",
        {
            "report": report,
        },
    )

@admin_required
@require_POST
@transaction.atomic
def report_status(request, pk):
    report = get_object_or_404(
        ContentReport.objects.select_for_update().select_related(
            "reporter",
            "complaint",
            "complaint__user",
            "comment",
            "comment__author_user",
        ),
        pk=pk,
    )

    new_status = request.POST.get(
        "status",
        "",
    )

    allowed_statuses = {
        ContentReport.Status.REVIEWING,
        ContentReport.Status.RESOLVED,
        ContentReport.Status.REJECTED,
        ContentReport.Status.ABUSIVE,
    }

    if new_status not in allowed_statuses:
        messages.error(
            request,
            "Geçersiz rapor durumu.",
        )

        return redirect(
            "adminx:report_detail",
            pk=report.pk,
        )

    previous_status = report.status

    terminal_statuses = {
        ContentReport.Status.RESOLVED,
        ContentReport.Status.REJECTED,
        ContentReport.Status.ABUSIVE,
    }

    # Sonuçlandırılmış raporların kararı daha sonra değiştirilemez.
    if (
        previous_status in terminal_statuses
        and new_status != previous_status
    ):
        messages.warning(
            request,
            "Bu rapor daha önce sonuçlandırılmış. "
            "Moderasyon kararı değiştirilemez.",
        )

        return redirect(
            "adminx:report_detail",
            pk=report.pk,
        )

    complaint_to_remove = None

    if (
        new_status == ContentReport.Status.RESOLVED
        and report.target_type == ContentReport.TargetType.COMPLAINT
        and report.complaint_id
    ):
        complaint_to_remove = get_object_or_404(
            Complaint.objects.select_for_update(),
            pk=report.complaint_id,
        )

    # Aynı durum tekrar gönderildiyse normalde işlem yapma.
    # Ancak eski bir RESOLVED raporda şikayet henüz kaldırılmadıysa
    # kaldırma işlemini tamamlamaya izin ver.
    if previous_status == new_status:
        needs_violation_removal = (
            new_status == ContentReport.Status.RESOLVED
            and complaint_to_remove is not None
            and not complaint_to_remove.removed_for_violation
        )

        if not needs_violation_removal:
            messages.info(
                request,
                "Rapor zaten bu durumda.",
            )

            return redirect(
                "adminx:report_detail",
                pk=report.pk,
            )

    report.status = new_status
    report.reviewed_by = request.user

    update_fields = [
        "status",
        "reviewed_by",
        "updated_at",
    ]

    if new_status in {
        ContentReport.Status.RESOLVED,
        ContentReport.Status.REJECTED,
        ContentReport.Status.ABUSIVE,
    }:
        report.reviewed_at = timezone.now()
        update_fields.append("reviewed_at")

    elif new_status == ContentReport.Status.REVIEWING:
        report.reviewed_at = None
        update_fields.append("reviewed_at")

    report.save(
        update_fields=update_fields,
    )

    violation = None

    # ---------------------------------------------------------
    # İÇERİK İHLALİ
    # ---------------------------------------------------------
    #
    # Admin gerçek içerik ihlali kararı verdiyse,
    # ihlal içerik sahibine yazılır.
    # ---------------------------------------------------------

    if new_status == ContentReport.Status.RESOLVED:
        violation_user = None
        source_type = None
        complaint_for_violation = None
        comment_for_violation = None

        if (
            report.target_type == ContentReport.TargetType.COMPLAINT
            and report.complaint_id
        ):
            violation_user = report.complaint.user
            source_type = UserViolation.SourceType.COMPLAINT
            complaint_for_violation = report.complaint

        elif (
            report.target_type == ContentReport.TargetType.COMMENT
            and report.comment_id
        ):
            violation_user = report.comment.author_user
            source_type = UserViolation.SourceType.COMMENT
            comment_for_violation = report.comment

        if violation_user and source_type:
            violation, violation_created = (
                UserViolation.objects.get_or_create(
                    content_report=report,
                    defaults={
                        "user": violation_user,
                        "source_type": source_type,
                        "reason": report.reason,
                        "description": (
                            f"{report.get_reason_display()} nedeniyle "
                            "içerik ihlali doğrulandı."
                        ),
                        "complaint": complaint_for_violation,
                        "comment": comment_for_violation,
                        "confirmed_by": request.user,
                    },
                )
            )

            if violation_created:
                record_admin_audit(
                    actor=request.user,
                    action=AdminAuditLog.Action.UPDATE,
                    target_type="user_violation",
                    target_id=violation.pk,
                    target_label=(
                        f"{violation_user.username} kullanıcısının "
                        "doğrulanmış ihlali"
                    ),
                    description=(
                        "Kullanıcı için doğrulanmış "
                        "topluluk kuralı ihlali oluşturuldu."
                    ),
                    metadata={
                        "user_id": violation_user.pk,
                        "username": violation_user.username,
                        "source_type": source_type,
                        "reason": report.reason,
                        "content_report_id": report.pk,
                    },
                    request=request,
                )

    # ---------------------------------------------------------
    # KÖTÜ NİYETLİ / ASILSIZ RAPOR
    # ---------------------------------------------------------
    #
    # Admin raporun kötü niyetli olduğunu açıkça seçerse,
    # ihlal raporlayan kullanıcıya yazılır.
    # ---------------------------------------------------------

    elif new_status == ContentReport.Status.ABUSIVE:
        reporter = report.reporter

        violation, violation_created = (
            UserViolation.objects.get_or_create(
                content_report=report,
                defaults={
                    "user": reporter,
                    "source_type": UserViolation.SourceType.FALSE_REPORT,
                    "reason": "FALSE_REPORT",
                    "description": (
                        "Gönderilen rapor kötü niyetli veya "
                        "asılsız raporlama olarak değerlendirildi."
                    ),
                    "confirmed_by": request.user,
                },
            )
        )

        if violation_created:
            record_admin_audit(
                actor=request.user,
                action=AdminAuditLog.Action.UPDATE,
                target_type="user_violation",
                target_id=violation.pk,
                target_label=(
                    f"{reporter.username} kullanıcısının "
                    "kötü niyetli raporlama ihlali"
                ),
                description=(
                    "Kullanıcı için kötü niyetli / asılsız "
                    "raporlama ihlali oluşturuldu."
                ),
                metadata={
                    "user_id": reporter.pk,
                    "username": reporter.username,
                    "source_type": UserViolation.SourceType.FALSE_REPORT,
                    "reason": "FALSE_REPORT",
                    "content_report_id": report.pk,
                },
                request=request,
            )

            from notifications.services import send
            from notifications.models import Notification

            send(
                recipient=reporter,
                scope="USER",
                kind="REPORT_ABUSE",
                event_key=f"content-report:{report.pk}:abusive",
                title="Raporunuz kötüye kullanım olarak değerlendirildi.",
                message=(
                    "Gönderdiğiniz raporun kötü niyetli veya asılsız "
                    "olduğu tespit edildi. Bu işlem hesabınıza "
                    "doğrulanmış ihlal olarak işlendi."
                ),
            )

    complaint_removed = False

    # ---------------------------------------------------------
    # ŞİKAYET İHLAL NEDENİYLE KALDIRMA
    # ---------------------------------------------------------

    if complaint_to_remove is not None:
        complaint_previous_status = complaint_to_remove.status

        complaint_to_remove.status = Complaint.Status.REMOVED
        complaint_to_remove.removed_for_violation = True
        complaint_to_remove.violation_removed_at = timezone.now()
        complaint_to_remove.violation_removed_by = request.user
        complaint_to_remove.violation_reason = report.reason
        complaint_to_remove.violation_report = report

        complaint_to_remove.save(
            update_fields=(
                "status",
                "removed_for_violation",
                "violation_removed_at",
                "violation_removed_by",
                "violation_reason",
                "violation_report",
                "updated_at",
            )
        )

        complaint_removed = True

        record_admin_audit(
            actor=request.user,
            action=AdminAuditLog.Action.UPDATE,
            target_type="complaint",
            target_id=complaint_to_remove.pk,
            target_label=complaint_to_remove.title,
            description=(
                "Şikayet ihlal nedeniyle yayından kaldırıldı."
            ),
            metadata={
                "previous_status": complaint_previous_status,
                "new_status": Complaint.Status.REMOVED,
                "violation_reason": report.reason,
                "content_report_id": report.pk,
            },
            request=request,
        )


    if report.target_type == ContentReport.TargetType.COMPLAINT:
        target_label = (
            report.complaint.title
            if report.complaint
            else f"Şikayet raporu #{report.pk}"
        )

    elif report.target_type == ContentReport.TargetType.COMMENT:
        target_label = (
            f"Yorum #{report.comment_id}"
            if report.comment_id
            else f"Yorum raporu #{report.pk}"
        )

    else:
        target_label = f"Rapor #{report.pk}"

    record_admin_audit(
        actor=request.user,
        action=AdminAuditLog.Action.UPDATE,
        target_type="content_report",
        target_id=report.pk,
        target_label=target_label,
        description="İçerik raporu durumu güncellendi.",
        metadata={
            "previous_status": previous_status,
            "new_status": new_status,
            "report_target_type": report.target_type,
            "report_reason": report.reason,
            "complaint_removed": complaint_removed,
            "user_violation_id": (
                violation.pk
                if violation
                else None
            ),
        },
        request=request,
    )

    # ---------------------------------------------------------
    # ADMIN MESAJI
    # ---------------------------------------------------------

    if new_status == ContentReport.Status.REVIEWING:
        message = "Rapor incelemeye alındı."

    elif new_status == ContentReport.Status.RESOLVED:
        if complaint_removed:
            message = (
                "Rapor sonuçlandırıldı ve şikayet "
                "ihlal nedeniyle kaldırıldı."
            )

        elif report.target_type == ContentReport.TargetType.COMMENT:
            message = (
                "Rapor sonuçlandırıldı ve kullanıcı için "
                "doğrulanmış ihlal kaydı oluşturuldu."
            )

        else:
            message = "Rapor sonuçlandırıldı."

    elif new_status == ContentReport.Status.ABUSIVE:
        message = (
            "Rapor kötü niyetli / asılsız olarak işaretlendi "
            "ve raporlayan kullanıcıya doğrulanmış ihlal eklendi."
        )

    else:
        message = "Raporda ihlal bulunmadı."

    messages.success(
        request,
        message,
    )

    return redirect(
        "adminx:report_detail",
        pk=report.pk,
    )