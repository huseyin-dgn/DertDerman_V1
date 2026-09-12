from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone
from datetime import timedelta
from core.pagination import paginate
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe
from .anti_abuse import (
    check_complaint_submission,
    mark_complaint_form_opened,
    reset_complaint_form_timer,
)
from accounts.models import User
from core.decorators import role_required

from .forms import (
    ComplaintCommentForm,
    ComplaintCreateForm,
    ComplaintEditForm,
    ContentReportForm,
    UserReportForm,
)
from .models import (
    Complaint,
    ComplaintComment,
    ComplaintLike,
    ComplaintReaction,
    ContentReport,
    UserReport,
)
from .selectors import public_complaints
from .services import ComplaintStateConflict, resolve_complaint
from .validators import validate_single_emoji
from .reporting_policy import (
    check_complaint_creation_allowed,
    check_general_reporting_allowed,
    check_user_report_allowed,
)
from django.core.exceptions import ValidationError



def _suspended_response(request):
    if (
        request.user.is_authenticated
        and getattr(request.user, "is_currently_suspended", False)
    ):
        messages.error(
            request,
            "Hesabınız askıya alındığı için bu işlemi gerçekleştiremezsiniz.",
        )
        return redirect("accounts:profile")

    return None


@require_safe
def public_complaint_list(request):
    complaints = public_complaints()
    search = request.GET.get("q", "").strip()[:100]
    active_filter = request.GET.get("status", "all")

    if search:
        complaints = complaints.filter(
            Q(title__icontains=search)
            | Q(company__name__icontains=search)
        )

    if active_filter == "published":
        complaints = complaints.filter(
            status=Complaint.Status.PUBLISHED
        )

    elif active_filter == "resolved":
        complaints = complaints.filter(
            status=Complaint.Status.RESOLVED
        )

    elif active_filter == "answered":
        complaints = complaints.filter(
            has_response=True
        )

    elif active_filter != "all":
        active_filter = "all"

    page_obj = paginate(
        request,
        complaints,
        "public_complaints"
    )

    return render(
        request,
        "complaints/public_list.html",
        {
            "page_obj": page_obj,
            "search": search,
            "active_filter": active_filter,
            "filter_options": (
                ("all", "Tümü"),
                ("published", "Yayında"),
                ("answered", "Şirket Cevapladı"),
                ("resolved", "Çözüldü"),
            ),
        },
    )


def _public_detail_context(
    request,
    complaint,
    *,
    comment_form=None,
):
    from companies.panel_selectors import company_responses
    from accounts.badges import (
        primary_badge,
        resolve_badges_for_users,
    )

    responses = company_responses(
        complaint.company
    ).filter(
        complaint=complaint
    )

    comments = ComplaintComment.objects.filter(
        complaint=complaint,
        is_active=True
    ).annotate(
        author_username=F(
            "author_user__username"
        ),
        author_first_name=F(
            "author_user__first_name"
        ),
        author_selected_avatar=F(
            "author_user__selected_avatar"
        ),
    )

    reaction_counts = dict(
        complaint.reactions
        .values_list(
            "reaction_type"
        )
        .annotate(
            total=Count("pk")
        )
    )

    liked = False
    active_reaction = ""

    if (
        request.user.is_authenticated
        and request.user.user_type == User.UserType.USER
    ):
        liked = ComplaintLike.objects.filter(
            complaint=complaint,
            user=request.user
        ).exists()

        active_reaction = (
            ComplaintReaction.objects.filter(
                complaint=complaint,
                user=request.user
            )
            .values_list(
                "reaction_type",
                flat=True
            )
            .first()
            or ""
        )

    common_emojis = (
        "😀",
        "😂",
        "👍",
        "❤️",
        "😮",
        "😕",
        "👏",
        "🤝",
        "🎉",
        "🙏",
    )

    reaction_options = [
        {
            "value": value,
            "count": reaction_counts.get(
                value,
                0
            ),
            "active": (
                active_reaction == value
            ),
        }
        for value in dict.fromkeys(
            (
                *common_emojis,
                *reaction_counts.keys()
            )
        )
    ]

    comment_page = paginate(
        request,
        comments,
        "public_comments",
        page_param="comment_page"
    )

    badge_map = resolve_badges_for_users(
        (
            complaint.user_id,
            *(
                comment.author_user_id
                for comment
                in comment_page.object_list
            )
        )
    )

    for comment in comment_page.object_list:
        comment.display_badge = primary_badge(
            badge_map.get(
                comment.author_user_id,
                ()
            )
        )

    return {
        "complaint": complaint,

        "company_response_page": paginate(
            request,
            responses,
            "company_responses",
            page_param="response_page"
        ),

        "comment_page": comment_page,

        "complaint_badge": primary_badge(
            badge_map.get(
                complaint.user_id,
                ()
            )
        ),

        "comment_form": (
            comment_form
            if comment_form is not None
            else ComplaintCommentForm()
        ),

        "content_report_form":
            ContentReportForm(),

        "liked": liked,
        "active_reaction": active_reaction,
        "reaction_options": reaction_options,
    }


@require_safe
def public_complaint_detail(request, pk):
    complaint = get_object_or_404(
        public_complaints(),
        pk=pk
    )

    return render(
        request,
        "complaints/public_detail.html",
        _public_detail_context(
            request,
            complaint
        ),
    )


@role_required(User.UserType.USER)
@require_POST
def complaint_like_toggle(request, pk):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    complaint = get_object_or_404(
        public_complaints(),
        pk=pk
    )

    with transaction.atomic():
        like, created = (
            ComplaintLike.objects
            .get_or_create(
                complaint=complaint,
                user=request.user
            )
        )

        if not created:
            like.delete()

    if created:
        from notifications.services import (
            complaint_social_event
        )

        complaint_social_event(
            complaint=complaint,
            actor=request.user,
            kind="LIKE",
            event_key=(
                f"social:like:"
                f"{complaint.pk}:"
                f"{request.user.pk}"
            ),
        )

    return redirect(
        "complaints:public_detail",
        pk=pk
    )


@role_required(User.UserType.USER)
@require_POST
def complaint_react(request, pk):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    complaint = get_object_or_404(
        public_complaints(),
        pk=pk
    )

    try:
        reaction_type = validate_single_emoji(
            request.POST.get(
                "reaction_type",
                ""
            )
        )

    except ValidationError as error:
        messages.error(
            request,
            error.messages[0]
        )

        return redirect(
            "complaints:public_detail",
            pk=pk
        )

    with transaction.atomic():
        current = (
            ComplaintReaction.objects
            .select_for_update()
            .filter(
                complaint=complaint,
                user=request.user
            )
            .first()
        )

        if (
            current
            and current.reaction_type == reaction_type
        ):
            current.delete()
            created = False

        elif current:
            current.reaction_type = reaction_type

            current.save(
                update_fields=(
                    "reaction_type",
                    "updated_at"
                )
            )

            created = False

        else:
            ComplaintReaction.objects.create(
                complaint=complaint,
                user=request.user,
                reaction_type=reaction_type
            )

            created = True

    if created:
        from notifications.services import (
            complaint_social_event
        )

        complaint_social_event(
            complaint=complaint,
            actor=request.user,
            kind="REACTION",
            event_key=(
                f"social:reaction:"
                f"{complaint.pk}:"
                f"{request.user.pk}"
            ),
        )

    return redirect(
        "complaints:public_detail",
        pk=pk
    )


@role_required(User.UserType.USER)
@require_POST
def complaint_comment_create(
    request,
    pk
):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    complaint = get_object_or_404(
        public_complaints(),
        pk=pk
    )

    form = ComplaintCommentForm(
        request.POST
    )

    if not form.is_valid():
        return render(
            request,
            "complaints/public_detail.html",
            _public_detail_context(
                request,
                complaint,
                comment_form=form
            ),
            status=400,
        )

    comment = form.save(
        commit=False
    )

    comment.complaint = complaint
    comment.author_user = request.user
    comment.save()

    from notifications.services import (
        complaint_social_event
    )

    complaint_social_event(
        complaint=complaint,
        actor=request.user,
        kind="COMMENT",
        event_key=(
            f"social:comment:"
            f"{comment.pk}"
        ),
    )

    messages.success(
        request,
        "Yorumunuz yayınlandı."
    )

    return redirect(
        "complaints:public_detail",
        pk=pk
    )


@role_required(User.UserType.USER)
@require_POST
def complaint_comment_delete(
    request,
    pk,
    comment_pk
):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    complaint = get_object_or_404(
        public_complaints(),
        pk=pk
    )

    comment = get_object_or_404(
        ComplaintComment,
        pk=comment_pk,
        complaint=complaint,
        author_user=request.user,
        is_active=True,
    )

    comment.is_active = False

    comment.save(
        update_fields=(
            "is_active",
            "updated_at"
        )
    )

    messages.success(
        request,
        "Yorumunuz kaldırıldı."
    )

    return redirect(
        "complaints:public_detail",
        pk=pk
    )


@role_required(User.UserType.USER)
@require_POST
def complaint_report(request, pk):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    reporting_policy = check_general_reporting_allowed(
        user=request.user,
        request=request,
    )
    if not reporting_policy.allowed:
        messages.error(
            request,
            reporting_policy.message,
        )
        return redirect(
            "complaints:public_detail",
            pk=pk,
        )

    complaint = get_object_or_404(
        public_complaints(),
        pk=pk,
    )

    # Kullanıcı kendi şikayetini raporlayamaz.
    if complaint.user_id == request.user.pk:
        messages.warning(
            request,
            "Kendi şikayetinizi raporlayamazsınız.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    # Aynı kullanıcı aynı şikayeti yalnızca bir kez raporlayabilir.
    if ContentReport.objects.filter(
        reporter=request.user,
        complaint=complaint,
    ).exists():
        messages.info(
            request,
            "Bu şikayeti daha önce raporladınız.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    form = ContentReportForm(
        request.POST
    )

    if not form.is_valid():
        messages.error(
            request,
            "Rapor gönderilemedi. "
            "Lütfen geçerli bir neden seçin.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    report = form.save(
        commit=False
    )

    report.reporter = request.user
    report.target_type = (
        ContentReport.TargetType.COMPLAINT
    )

    report.complaint = complaint
    report.comment = None
    report.status = (
        ContentReport.Status.PENDING
    )

    try:
        with transaction.atomic():
            report.save()

            from notifications.services import (
                notify_admins_content_report
            )

            notify_admins_content_report(
                report
            )

    except (
        ValidationError,
        IntegrityError
    ):
        messages.info(
            request,
            "Bu şikayeti daha önce raporladınız.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    messages.success(
        request,
        "Raporunuz alındı. "
        "İçerik yönetim ekibi tarafından incelenecek.",
    )

    return redirect(
        "complaints:public_detail",
        pk=complaint.pk,
    )


@role_required(User.UserType.USER)
@require_POST
def comment_report(
    request,
    pk,
    comment_pk
):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    reporting_policy = check_general_reporting_allowed(
        user=request.user,
        request=request,
    )
    if not reporting_policy.allowed:
        messages.error(
            request,
            reporting_policy.message,
        )
        return redirect(
            "complaints:public_detail",
            pk=pk,
        )

    complaint = get_object_or_404(
        public_complaints(),
        pk=pk,
    )

    comment = get_object_or_404(
        ComplaintComment,
        pk=comment_pk,
        complaint=complaint,
        is_active=True,
    )

    if (
        comment.author_user_id
        == request.user.pk
    ):
        messages.warning(
            request,
            "Kendi yorumunuzu raporlayamazsınız.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    if ContentReport.objects.filter(
        reporter=request.user,
        comment=comment,
    ).exists():
        messages.info(
            request,
            "Bu yorumu daha önce raporladınız.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    form = ContentReportForm(
        request.POST
    )

    if not form.is_valid():
        messages.error(
            request,
            "Rapor gönderilemedi. "
            "Lütfen geçerli bir neden seçin.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    report = form.save(
        commit=False
    )

    report.reporter = request.user
    report.target_type = (
        ContentReport.TargetType.COMMENT
    )

    report.complaint = None
    report.comment = comment
    report.status = (
        ContentReport.Status.PENDING
    )

    try:
        with transaction.atomic():
            report.save()

            from notifications.services import (
                notify_admins_content_report
            )

            notify_admins_content_report(
                report
            )

    except (
        ValidationError,
        IntegrityError
    ):
        messages.info(
            request,
            "Bu yorumu daha önce raporladınız.",
        )

        return redirect(
            "complaints:public_detail",
            pk=complaint.pk,
        )

    messages.success(
        request,
        "Raporunuz alındı. "
        "Yorum yönetim ekibi tarafından incelenecek.",
    )

    return redirect(
        "complaints:public_detail",
        pk=complaint.pk,
    )



@role_required(User.UserType.USER)
@require_POST
def user_report(request, user_pk):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    reporting_policy = check_user_report_allowed(
        user=request.user,
        request=request,
    )
    if not reporting_policy.allowed:
        messages.error(
            request,
            reporting_policy.message,
        )
        return redirect(
            "accounts:public_profile",
            username=(
                User.objects
                .filter(pk=user_pk)
                .values_list(
                    "username",
                    flat=True,
                )
                .first()
                or request.user.username
            ),
        )

    reported_user = get_object_or_404(
        User.objects.only(
            "pk",
            "username",
            "user_type",
            "is_active",
        ),
        pk=user_pk,
        user_type=User.UserType.USER,
        is_active=True,
    )

    if reported_user.pk == request.user.pk:
        messages.warning(
            request,
            "Kendi hesabınızı raporlayamazsınız.",
        )
        return redirect(
            "accounts:public_profile",
            username=reported_user.username,
        )

    if UserReport.objects.filter(
        reporter=request.user,
        reported_user=reported_user,
    ).exists():
        messages.info(
            request,
            "Bu kullanıcıyı daha önce raporladınız.",
        )
        return redirect(
            "accounts:public_profile",
            username=reported_user.username,
        )

    form = UserReportForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "Rapor gönderilemedi. Lütfen geçerli bir neden seçin.",
        )
        return redirect(
            "accounts:public_profile",
            username=reported_user.username,
        )

    report = form.save(commit=False)
    report.reporter = request.user
    report.reported_user = reported_user
    report.status = UserReport.Status.PENDING

    try:
        with transaction.atomic():
            report.save()

            from notifications.services import notify_admins_user_report

            notify_admins_user_report(report)

    except (ValidationError, IntegrityError):
        messages.info(
            request,
            "Bu kullanıcıyı daha önce raporladınız.",
        )
        return redirect(
            "accounts:public_profile",
            username=reported_user.username,
        )

    messages.success(
        request,
        "Kullanıcı raporunuz alındı ve yönetim ekibine iletildi.",
    )

    return redirect(
        "accounts:public_profile",
        username=reported_user.username,
    )


@role_required(User.UserType.USER)
@require_safe
def complaint_list(request):
    from companies.models import (
        CompanyResponse
    )

    complaints = (
        Complaint.objects
        .filter(
            user=request.user
        )
        .select_related(
            "company"
        )
        .annotate(
            has_response=Exists(
                CompanyResponse.objects.filter(
                    complaint_id=OuterRef("pk"),
                    company_id=OuterRef(
                        "company_id"
                    ),
                    is_active=True
                )
            )
        )
        .order_by(
            "-created_at",
            "-pk"
        )
    )

    search = request.GET.get(
        "q",
        ""
    ).strip()[:100]

    active_filter = request.GET.get(
        "status",
        "all"
    )

    if search:
        complaints = complaints.filter(
            Q(
                title__icontains=search
            )
            | Q(
                company__name__icontains=search
            )
        )

    if active_filter == "pending":
        complaints = complaints.filter(
            status=Complaint.Status.PENDING
        )

    elif active_filter == "published":
        complaints = complaints.filter(
            status=Complaint.Status.PUBLISHED
        )

    elif active_filter == "answered":
        complaints = complaints.filter(
            has_response=True
        )

    elif active_filter == "resolved":
        complaints = complaints.filter(
            status=Complaint.Status.RESOLVED
        )

    elif active_filter != "all":
        active_filter = "all"

    page = paginate(
        request,
        complaints,
        "user_complaints"
    )

    return render(
        request,
        "complaints/complaint_list.html",
        {
            "complaints": page,
            "page_obj": page,
            "active_filter": active_filter,
            "search": search,

            "filter_options": (
                (
                    "all",
                    "Tümü"
                ),
                (
                    "pending",
                    "İncelemede"
                ),
                (
                    "published",
                    "Yayında"
                ),
                (
                    "answered",
                    "Şirket Cevapladı"
                ),
                (
                    "resolved",
                    "Çözüldü"
                ),
            ),
        },
    )


@role_required(User.UserType.USER)
@require_safe
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.select_related(
            "company"
        ),
        pk=pk,
        user=request.user
    )

    from companies.panel_selectors import (
        company_responses
    )

    return render(
        request,
        "complaints/complaint_detail.html",
        {
            "complaint": complaint,

            "timeline_events":
                complaint.timeline_events.all(),

            "company_response_page":
                paginate(
                    request,
                    company_responses(
                        complaint.company
                    ).filter(
                        complaint=complaint
                    ),
                    "company_responses",
                    page_param="response_page"
                ),
        },
    )


@role_required(User.UserType.USER)
def complaint_edit(request, pk):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    complaint = get_object_or_404(
        Complaint,
        pk=pk,
        user=request.user
    )

    if (
        complaint.withdrawn_at
        or complaint.status
        == Complaint.Status.RESOLVED
    ):
        return render(
            request,
            "complaints/complaint_edit.html",
            {
                "complaint": complaint,
                "edit_blocked": True,
            },
            status=403
        )

    if request.method == "POST":
        form = ComplaintEditForm(
            request.POST,
            instance=complaint
        )

        if form.is_valid():
            from .services import (
                edit_complaint
            )

            edit_complaint(
                complaint=complaint,
                form=form,
                actor=request.user
            )

            messages.success(
                request,
                "Şikayetiniz güncellendi "
                "ve incelemeye gönderildi."
            )

            return redirect(
                "complaints:detail",
                pk=complaint.pk
            )

    else:
        form = ComplaintEditForm(
            instance=complaint
        )

    return render(
        request,
        "complaints/complaint_edit.html",
        {
            "complaint": complaint,
            "form": form
        }
    )


@role_required(User.UserType.USER)
@require_POST
def complaint_withdraw(
    request,
    pk
):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    complaint = get_object_or_404(
        Complaint,
        pk=pk,
        user=request.user
    )

    from .services import (
        withdraw_complaint
    )

    withdraw_complaint(
        complaint=complaint,
        actor=request.user
    )

    messages.success(
        request,
        "Şikayetiniz geri çekildi."
    )

    return redirect(
        "complaints:detail",
        pk=complaint.pk
    )


@role_required(User.UserType.USER)
@require_POST
def complaint_resolve(
    request,
    pk
):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    get_object_or_404(
        Complaint.objects.only(
            "pk"
        ),
        pk=pk,
        user=request.user
    )

    try:
        resolve_complaint(
            complaint_id=pk,
            actor=request.user,
            owner_id=request.user.pk
        )

    except ComplaintStateConflict:
        messages.warning(
            request,
            "Yalnızca yayındaki bir şikayet "
            "çözüldü olarak işaretlenebilir."
        )

    else:
        messages.success(
            request,
            "Sorunun çözüldüğünü onayladınız."
        )

    return redirect(
        "complaints:detail",
        pk=pk
    )

@role_required(User.UserType.USER)
@transaction.atomic
def complaint_create(request):
    blocked = _suspended_response(request)
    if blocked:
        return blocked

    complaint_policy = check_complaint_creation_allowed(
        user=request.user,
        request=request,
    )
    if not complaint_policy.allowed:
        messages.error(
            request,
            complaint_policy.message,
        )
        return redirect(
            "dashboard:home"
        )

    if request.method == "POST":
        form = ComplaintCreateForm(
            request.POST
        )

        if form.is_valid():
            # ------------------------------------------------
            # Aynı kullanıcının eş zamanlı gönderimlerini
            # serialize ediyoruz.
            # ------------------------------------------------

            locked_user = (
                User.objects
                .select_for_update()
                .get(
                    pk=request.user.pk
                )
            )

            # ------------------------------------------------
            # ANTI-ABUSE KONTROLÜ
            # ------------------------------------------------

            anti_abuse_result = (
                check_complaint_submission(
                    request=request,
                    user=locked_user,
                    company=form.cleaned_data[
                        "company"
                    ],
                    title=form.cleaned_data[
                        "title"
                    ],
                    description=form.cleaned_data[
                        "description"
                    ],
                )
            )

            if not anti_abuse_result.allowed:
                messages.error(
                    request,
                    anti_abuse_result.message
                )

                # Form yeniden gösterildiği için yeni zaman
                # başlangıcı oluşturuyoruz.
                mark_complaint_form_opened(
                    request
                )

                return render(
                    request,
                    "complaints/complaint_create.html",
                    {
                        "form": form
                    },
                    status=429,
                )

            # ------------------------------------------------
            # ŞİKAYET OLUŞTUR
            # ------------------------------------------------

            complaint = form.save(
                commit=False
            )

            complaint.user = locked_user

            complaint.status = (
                Complaint.Status.PENDING
            )

            complaint.save()

            # Başarılı gönderimden sonra form timer temizlenir.
            reset_complaint_form_timer(
                request
            )

            messages.success(
                request,
                "Şikayetiniz incelemeye alındı. "
                "Yayınlanmadan önce değerlendirilecektir.",
            )

            return redirect(
                "dashboard:home"
            )

    else:
        # ----------------------------------------------------
        # FORM GET İLE AÇILDI
        # ----------------------------------------------------

        mark_complaint_form_opened(
            request
        )

        initial_company = None

        company_id = request.GET.get(
            "company",
            ""
        )

        if company_id.isdigit():
            from companies.selectors import (
                public_companies
            )

            initial_company = (
                public_companies()
                .filter(
                    pk=company_id
                )
                .first()
            )

        form = ComplaintCreateForm(
            initial={
                "company": initial_company
            }
            if initial_company
            else None
        )

    return render(
        request,
        "complaints/complaint_create.html",
        {
            "form": form
        }
    )