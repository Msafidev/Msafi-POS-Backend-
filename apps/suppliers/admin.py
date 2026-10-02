from django.contrib import admin
from apps.suppliers.models import Supplier, SupplierInvoice


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "phone", "is_active")
    list_filter = ("business", "is_active")
    search_fields = ("name", "phone", "email")


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = ("reference", "supplier", "amount", "is_paid", "due_date")
    list_filter = ("is_paid",)
