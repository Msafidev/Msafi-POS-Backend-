from django.contrib import admin

from apps.tax.models import ETIMSInvoice, TaxProfile, TaxRecord


@admin.register(TaxProfile)
class TaxProfileAdmin(admin.ModelAdmin):
    list_display = ["business", "etims_enabled", "etims_environment", "updated_at"]
    search_fields = ["business__name"]


@admin.register(TaxRecord)
class TaxRecordAdmin(admin.ModelAdmin):
    list_display = ["business", "tax_type", "period_start", "period_end", "amount", "is_estimated"]
    list_filter = ["tax_type", "is_estimated"]
    search_fields = ["business__name"]


@admin.register(ETIMSInvoice)
class ETIMSInvoiceAdmin(admin.ModelAdmin):
    list_display = ["business", "sale", "status", "kra_invoice_number", "created_at"]
    list_filter = ["status"]
    search_fields = ["business__name", "kra_invoice_number", "sale__sequence_no"]
    readonly_fields = ["raw_response"]
