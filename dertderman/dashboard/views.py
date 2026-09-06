from django.shortcuts import render

from accounts.models import User
from complaints.models import Complaint
from core.decorators import role_required


@role_required(User.UserType.USER)
def home(request):
    recent_complaints = (
        Complaint.objects.filter(user=request.user)
        .select_related("company")
        .order_by("-created_at", "-pk")[:3]
    )
    return render(
        request,
        "dashboard/home.html",
        {"recent_complaints": recent_complaints},
    )
