from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe
from core.decorators import role_required
from core.pagination import paginate
from .selectors import inbox
from .services import mark_read


@role_required('USER')
@require_safe
def notification_list(request):
    return render(request, 'notifications/user_list.html', {
        'page_obj': paginate(request, inbox(request.user, 'USER'), 'user_notifications')})


@role_required('USER')
@require_safe
def notification_open(request, pk):
    notification = get_object_or_404(inbox(request.user, 'USER'), pk=pk)
    return redirect(notification.target_url)


@role_required('USER')
@require_POST
def notification_read(request, pk):
    notification = get_object_or_404(inbox(request.user, 'USER'), pk=pk)
    mark_read(inbox(request.user, 'USER').filter(pk=notification.pk))
    return redirect('notifications:list')


@role_required('USER')
@require_POST
def read_all(request):
    mark_read(inbox(request.user, 'USER'))
    return redirect('notifications:list')
