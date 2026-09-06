from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
def csrf_failure(request, reason=""):
    # Do not reflect token, reason, URL or other request internals.
    return render(request, "csrf_failure.html", status=403)
