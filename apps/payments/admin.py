from django.contrib import admin

from apps.payments.models import PaymentProvider, PaymentTransaction


@admin.register(PaymentProvider)
class PaymentProviderAdmin(admin.ModelAdmin):
    list_display = ("business", "provider", "display_name", "sandbox", "active", "created_at")
    list_filter = ("provider", "sandbox", "active")
    search_fields = ("business__name", "display_name")


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("business", "provider", "amount", "status", "provider_reference", "created_at")
    list_filter = ("status", "provider__provider")
    search_fields = ("business__name", "provider_reference", "checkout_request_id")
    readonly_fields = ("raw_response",)
