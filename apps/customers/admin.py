from django.contrib import admin
from apps.customers.models import Customer, CustomerGroup, CustomerNote


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "phone", "loyalty_points", "credit_balance", "is_active")
    list_filter = ("business", "group", "is_active")
    search_fields = ("name", "phone", "email")


@admin.register(CustomerGroup)
class CustomerGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "default_discount_percent")


@admin.register(CustomerNote)
class CustomerNoteAdmin(admin.ModelAdmin):
    list_display = ("customer", "author", "created_at")
