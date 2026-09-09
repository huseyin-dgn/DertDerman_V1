from django.utils.functional import SimpleLazyObject
from .selectors import inbox


def notification_badge(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or user.user_type not in ('USER', 'ADMIN'):
        return {}
    # Evaluated only when a header renders it, once per request, using COUNT.
    return {'notification_unread_count': SimpleLazyObject(
        lambda: inbox(user, user.user_type).filter(is_read=False).count())}
