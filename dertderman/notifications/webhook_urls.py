from django.urls import path
from .webhook_views import resend_webhook

app_name = "notification_webhooks"
urlpatterns = [path("resend/", resend_webhook, name="resend")]
