from django.contrib import admin
from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "business", "type", "is_read", "created_at")
    list_filter = ("business", "type", "is_read")
