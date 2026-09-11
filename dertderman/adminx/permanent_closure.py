from django.contrib import messages
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe

from accounts.models import User
from complaints.models import Complaint
from complaints.reporting_policy import (
    false_report_category_counts,
    permanent_close_eligible,
)
from core.pagination import paginate

from .decorators import admin_required
from .models import AdminAuditLog
from .services import record_admin_audit


MIN_REASON_LENGTH = 10
MAX_REASON_LENGTH = 1000


def _delete_user_sessions(user_id):
    target = str(user_id)

    for session in Session.objects.all().iterator(chunk_size=500):
        try:
            auth_user_id = session.get_decoded().get("_auth_user_id")
        except Exception:
            continue

        if auth_user_id == target:
            session.delete()


def _soft_remove_user_complaints(account, actor, closed_at):
    queryset = Complaint.objects.filter(user=account).exclude(
        status=Complaint.Status.REMOVED
    )

    update_values = {
        "status": Complaint.Status.REMOVED,
        "updated_at": closed_at,
    }

    field_names = {field.name for field in Complaint._meta.get_fields()}

    if "removed_for_violation" in field_names:
        update_values["removed_for_violation"] = True

    if "violation_removed_at" in field_names:
        update_values["violation_removed_at"] = closed_at

    if "violation_removed_by" in field_names:
        update_values["violation_removed_by"] = actor

    return queryset.update(**update_values)


@admin_required
@require_POST
@never_cache
@transaction.atomic
def permanently_close_user(request, pk):
    account = get_object_or_404(
        User.objects.select_for_update(),
        pk=pk,
    )

    if account.user_type != User.UserType.USER:
        messages.error(
            request,
            "Yalnızca bireysel kullanıcı hesapları bu işlemle kapatılabilir.",
        )
        return redirect("adminx:user_detail", pk=account.pk)

    if account.pk == request.user.pk:
        messages.error(
            request,
            "Kendi hesabınızı bu işlemle kapatamazsınız.",
        )
        return redirect("adminx:user_detail", pk=account.pk)

    if account.is_permanently_closed:
        messages.info(
            request,
            "Bu hesap zaten kalıcı olarak kapatılmış.",
        )
        return redirect("adminx:user_detail", pk=account.pk)

    # UI durumuna güvenilmez; eşik işlem anında server-side tekrar hesaplanır.
    if not permanent_close_eligible(account):
        messages.error(
            request,
            "Kullanıcı kalıcı kapatma kriterlerini artık karşılamıyor. İşlem uygulanmadı.",
        )
        return redirect("adminx:user_detail", pk=account.pk)

    confirm_username = (
        request.POST.get("confirm_username") or ""
    ).strip()

    reason = (
        request.POST.get("reason") or ""
    ).strip()

    if confirm_username != account.username:
        messages.error(
            request,
            "Güvenlik onayı başarısız. Kullanıcı adı tam olarak eşleşmelidir.",
        )
        return redirect("adminx:user_detail", pk=account.pk)

    if not (MIN_REASON_LENGTH <= len(reason) <= MAX_REASON_LENGTH):
        messages.error(
            request,
            f"Kapatma gerekçesi {MIN_REASON_LENGTH}-{MAX_REASON_LENGTH} karakter arasında olmalıdır.",
        )
        return redirect("adminx:user_detail", pk=account.pk)

    counts = false_report_category_counts(account)

    total_false_reports = (
        counts.get("user_report", 0)
        + counts.get("content_report", 0)
        + counts.get("company_report", 0)
    )

    closed_at = timezone.now()

    complaints_removed = _soft_remove_user_complaints(
        account=account,
        actor=request.user,
        closed_at=closed_at,
    )

    account.is_permanently_closed = True
    account.permanently_closed_at = closed_at
    account.permanently_closed_by = request.user
    account.permanent_closure_reason = reason
    account.permanent_closure_snapshot = {
        "user_report": counts.get("user_report", 0),
        "content_report": counts.get("content_report", 0),
        "company_report": counts.get("company_report", 0),
        "total_false_report": total_false_reports,
        "complaints_removed": complaints_removed,
    }
    account.is_active = False

    account.save(
        update_fields=(
            "is_permanently_closed",
            "permanently_closed_at",
            "permanently_closed_by",
            "permanent_closure_reason",
            "permanent_closure_snapshot",
            "is_active",
        )
    )

    record_admin_audit(
        actor=request.user,
        action=AdminAuditLog.Action.UPDATE,
        target_type="user",
        target_id=account.pk,
        target_label=account.username,
        description="Kullanıcı hesabı kalıcı olarak kapatıldı.",
        metadata={
            "reason": reason,
            "false_report_counts": counts,
            "total_false_report": total_false_reports,
            "complaints_removed": complaints_removed,
            "is_active": False,
            "is_permanently_closed": True,
        },
        request=request,
    )

    # Transaction başarısız olursa oturumlar boşuna silinmesin.
    transaction.on_commit(
        lambda: _delete_user_sessions(account.pk)
    )

    messages.success(
        request,
        f"@{account.username} hesabı kalıcı olarak kapatıldı ve aktif oturumları sonlandırıldı.",
    )

    return redirect(
        "adminx:user_detail",
        pk=account.pk,
    )


@admin_required
@require_safe
@never_cache
def closed_user_list(request):
    queryset = (
        User.objects
        .filter(
            user_type=User.UserType.USER,
            is_permanently_closed=True,
        )
        .select_related("permanently_closed_by")
        .order_by("-permanently_closed_at", "-pk")
    )

    search = (
        request.GET.get("q") or ""
    ).strip()[:100]

    if search:
        queryset = queryset.filter(
            Q(username__icontains=search)
            | Q(email__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(permanent_closure_reason__icontains=search)
        )

    page_obj = paginate(
        request,
        queryset,
        "admin",
    )

    return render(
        request,
        "adminx/closed_user_list.html",
        {
            "page_obj": page_obj,
            "search": search,
        },
    )
