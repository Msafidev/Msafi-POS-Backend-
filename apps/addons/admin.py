from django.contrib import admin

from apps.addons.models import AddOnPayment, AddOnSubscription


@admin.register(AddOnSubscription)
class AddOnSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("business", "feature", "expires_at", "is_active")
    list_filter = ("feature",)
    search_fields = ("business__name",)


@admin.register(AddOnPayment)
class AddOnPaymentAdmin(admin.ModelAdmin):
    list_display = ("business", "feature", "amount", "payment_method", "status", "created_at")
    list_filter = ("status", "feature", "payment_method")
    search_fields = ("business__name", "transaction_code", "payer_phone")
    readonly_fields = ("id", "created_at", "submitted_by", "verified_by", "verified_at")
