from django.db.models import Q
from .models import Notification


def inbox(user, scope):
    if not user.is_authenticated or not user.is_active or user.user_type != scope:
        return Notification.objects.none()
    result = Notification.objects.filter(recipient_user=user, recipient_role=scope)
    if scope == 'USER':
        result = result.filter(Q(complaint__isnull=True) | Q(complaint__user=user))
    else:
        result = result.order_by('-created_at', '-pk')
    return result.select_related('company', 'complaint')
