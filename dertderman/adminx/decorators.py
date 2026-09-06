from accounts.models import User
from core.decorators import role_required


admin_required = role_required(User.UserType.ADMIN, login_url="adminx:login")
