from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from django.urls import reverse

from .context import ActorKind, AssistantContext
from .selectors import (
    get_my_complaint_summary,
    get_my_notification_summary,
    get_my_summary,
)


class AssistantAction(str, Enum):
    ABOUT_DERTDERMAN = "ABOUT_DERTDERMAN"
    HOW_TO_COMPLAIN = "HOW_TO_COMPLAIN"
    WHAT_IS_DERMAN = "WHAT_IS_DERMAN"
    HOW_TO_REGISTER = "HOW_TO_REGISTER"
    HOW_TO_LOGIN = "HOW_TO_LOGIN"
    COMPANY_ACCOUNT_HELP = "COMPANY_ACCOUNT_HELP"
    MY_SUMMARY = "MY_SUMMARY"

    # A3 - context-aware, read-only USER helpers.
    MY_COMPLAINTS = "MY_COMPLAINTS"
    MY_NOTIFICATIONS = "MY_NOTIFICATIONS"
    ACCOUNT_SETTINGS = "ACCOUNT_SETTINGS"

    # A3 - public support helper.
    CONTACT_SUPPORT = "CONTACT_SUPPORT"


@dataclass(frozen=True)
class AssistantReply:
    message: str
    data: Mapping[str, object] | None = None
    links: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class ActionRule:
    allowed_actor_kinds: frozenset[ActorKind]
    handler: Callable[[AssistantContext], AssistantReply]
    requires_private_user: bool = False


PUBLIC_ACTORS = frozenset(
    {
        ActorKind.ANONYMOUS,
        ActorKind.USER,
        ActorKind.COMPANY,
        ActorKind.ADMIN,
    }
)

PRIVATE_USER_ACTORS = frozenset({ActorKind.USER})


def _link(label: str, route_name: str) -> dict[str, str]:
    return {
        "label": label,
        "url": reverse(route_name),
    }


def about_dertderman(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "DertDerman, kullanıcıların şikayetlerini paylaşabildiği, "
            "şirketlerin yetkili panel üzerinden süreçleri takip edebildiği "
            "bir şikayet platformudur."
        ),
        links=(
            _link("Hakkımızda", "core:about"),
            _link("Sık Sorulan Sorular", "core:faq"),
        ),
    )


def how_to_complain(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "Şikayet oluşturma işlemi asistan içinde yapılmaz. "
            "Güvenli şikayet oluşturma sayfasına yönlendirilirsiniz."
        ),
        links=(
            _link(
                "Şikayet Oluştur",
                "complaints:create",
            ),
        ),
    )


def what_is_derman(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "Derman Ol, yayınlanmış şikayetlerde kullanıcıların çözüm veya "
            "deneyim paylaşmasına ayrılan alandır. Asistan Derman oluşturmaz "
            "veya değiştirmez; yalnızca ilgili sayfalara yönlendirir."
        ),
        links=(
            _link(
                "Şikayetleri Gör",
                "complaints:public_list",
            ),
        ),
    )


def how_to_register(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "Bireysel kullanıcı kaydı hesap kayıt sayfasından yapılır. "
            "Asistan kayıt işlemini kendi içinde gerçekleştirmez."
        ),
        links=(
            _link(
                "Kayıt Ol",
                "accounts:register",
            ),
        ),
    )


def how_to_login(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "Bireysel kullanıcı girişi güvenli giriş sayfasından yapılır."
        ),
        links=(
            _link(
                "Giriş Yap",
                "accounts:login",
            ),
        ),
    )


def company_account_help(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "Şirket hesabı için kurumsal kayıt veya kurumsal giriş "
            "sayfalarını kullanabilirsiniz. Asistan şirket hesabı oluşturmaz "
            "ve şirket ayarlarını değiştirmez."
        ),
        links=(
            _link(
                "Kurumsal Kayıt",
                "company_auth:register",
            ),
            _link(
                "Kurumsal Giriş",
                "company_auth:login",
            ),
            _link(
                "Firmalar İçin",
                "core:for_companies",
            ),
        ),
    )


def my_summary(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message="Hesabınıza ait güvenli özet bilgileri aşağıdadır.",
        data=get_my_summary(context.user),
        links=(
            _link(
                "Şikayetlerim",
                "complaints:list",
            ),
            _link(
                "Bildirimlerim",
                "notifications:list",
            ),
        ),
    )


def my_complaints(
    context: AssistantContext,
) -> AssistantReply:
    summary = get_my_complaint_summary(context.user)
    total = summary["total"]
    latest = summary["latest"]

    if total == 0:
        message = (
            "Henüz hesabınıza ait bir şikayet bulunmuyor. "
            "Yeni bir şikayet oluşturabilir veya yayınlanan şikayetleri inceleyebilirsiniz."
        )
    elif latest:
        status_label = latest["status"]
        for item in summary["status_distribution"]:
            if item["status"] == latest["status"]:
                status_label = item["label"]
                break

        message = (
            f"Hesabınızda toplam {total} şikayet bulunuyor. "
            f"En son şikayetinizin durumu: {status_label}."
        )
    else:
        message = f"Hesabınızda toplam {total} şikayet bulunuyor."

    return AssistantReply(
        message=message,
        data=summary,
        links=(
            _link("Şikayetlerim", "complaints:list"),
            _link("Yeni Şikayet", "complaints:create"),
        ),
    )


def my_notifications(
    context: AssistantContext,
) -> AssistantReply:
    summary = get_my_notification_summary(context.user)
    unread_count = summary["unread_count"]

    if unread_count:
        message = (
            f"{unread_count} okunmamış bildiriminiz bulunuyor. "
            "Bildirimlerinizi güvenli bildirim sayfasından inceleyebilirsiniz."
        )
    else:
        message = "Şu anda okunmamış bildiriminiz bulunmuyor."

    return AssistantReply(
        message=message,
        data=summary,
        links=(
            _link("Bildirimlerim", "notifications:list"),
        ),
    )


def account_settings(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "Profil, e-posta ve parola işlemleri asistan içinde değiştirilmez. "
            "İlgili güvenli hesap sayfasına yönlendirilirsiniz."
        ),
        links=(
            _link("Profilim", "accounts:profile"),
            _link("Profili Düzenle", "accounts:profile_edit"),
            _link("E-posta Değiştir", "accounts:email_change"),
            _link("Parola Değiştir", "accounts:password_change"),
        ),
    )


def contact_support(
    context: AssistantContext,
) -> AssistantReply:
    return AssistantReply(
        message=(
            "Aradığınız yanıtı bulamadıysanız sık sorulan soruları inceleyebilir "
            "veya iletişim sayfasından DertDerman'a ulaşabilirsiniz."
        ),
        links=(
            _link("Sık Sorulan Sorular", "core:faq"),
            _link("Bize Ulaşın", "core:contact"),
        ),
    )


ACTION_RULES: dict[AssistantAction, ActionRule] = {
    AssistantAction.ABOUT_DERTDERMAN: ActionRule(
        allowed_actor_kinds=PUBLIC_ACTORS,
        handler=about_dertderman,
    ),
    AssistantAction.HOW_TO_COMPLAIN: ActionRule(
        allowed_actor_kinds=PUBLIC_ACTORS,
        handler=how_to_complain,
    ),
    AssistantAction.WHAT_IS_DERMAN: ActionRule(
        allowed_actor_kinds=PUBLIC_ACTORS,
        handler=what_is_derman,
    ),
    AssistantAction.HOW_TO_REGISTER: ActionRule(
        allowed_actor_kinds=PUBLIC_ACTORS,
        handler=how_to_register,
    ),
    AssistantAction.HOW_TO_LOGIN: ActionRule(
        allowed_actor_kinds=PUBLIC_ACTORS,
        handler=how_to_login,
    ),
    AssistantAction.COMPANY_ACCOUNT_HELP: ActionRule(
        allowed_actor_kinds=PUBLIC_ACTORS,
        handler=company_account_help,
    ),
    AssistantAction.MY_SUMMARY: ActionRule(
        allowed_actor_kinds=PRIVATE_USER_ACTORS,
        handler=my_summary,
        requires_private_user=True,
    ),
    AssistantAction.MY_COMPLAINTS: ActionRule(
        allowed_actor_kinds=PRIVATE_USER_ACTORS,
        handler=my_complaints,
        requires_private_user=True,
    ),
    AssistantAction.MY_NOTIFICATIONS: ActionRule(
        allowed_actor_kinds=PRIVATE_USER_ACTORS,
        handler=my_notifications,
        requires_private_user=True,
    ),
    AssistantAction.ACCOUNT_SETTINGS: ActionRule(
        allowed_actor_kinds=PRIVATE_USER_ACTORS,
        handler=account_settings,
        requires_private_user=True,
    ),
    AssistantAction.CONTACT_SUPPORT: ActionRule(
        allowed_actor_kinds=PUBLIC_ACTORS,
        handler=contact_support,
    ),
}
