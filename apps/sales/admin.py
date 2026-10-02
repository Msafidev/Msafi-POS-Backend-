from django.contrib import admin
from apps.sales.models import Sale, SaleItem, Payment, Refund, RefundItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("sale_number", "business", "customer", "cashier", "status", "total_amount", "created_at")
    list_filter = ("business", "status")
    inlines = [SaleItemInline, PaymentInline]
    readonly_fields = ("sequence_no",)


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("sale", "amount", "refund_method", "refunded_by", "created_at")
