from django.shortcuts import render

from accounts.models import User
from core.decorators import role_required


@role_required(User.UserType.ADMIN)
def home(request):
    return render(request, "adminx/home.html")
