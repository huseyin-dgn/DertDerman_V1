from django.urls import path
from . import views

app_name = 'notifications'
urlpatterns = [
    path('', views.notification_list, name='list'),
    path('<int:pk>/', views.notification_open, name='open'),
    path('<int:pk>/okundu/', views.notification_read, name='read'),
    path('tumunu-okundu/', views.read_all, name='read_all'),
]
