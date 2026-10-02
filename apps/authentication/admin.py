from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.authentication.models import User, ActivityLog


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "business", "branch", "is_active")
    list_filter = ("role", "business", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("MsafiPOS", {"fields": ("business", "branch", "role", "phone", "avatar", "is_email_verified", "must_change_password")}),
    )


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "business", "created_at")
    list_filter = ("action", "business")
    readonly_fields = [f.name for f in ActivityLog._meta.fields]
