from django.contrib import admin
from apps.inventory.models import (
    Category, Brand, Product, ProductVariant, ProductSerialNumber,
    StockMovement, PurchaseOrder, PurchaseOrderItem,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "parent", "is_active")
    list_filter = ("business", "is_active")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "is_active")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "business", "current_stock", "minimum_stock", "selling_price", "status")
    list_filter = ("business", "status", "category", "brand")
    search_fields = ("name", "sku", "barcode")
    inlines = [ProductVariantInline]


@admin.register(ProductSerialNumber)
class ProductSerialNumberAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "product", "is_sold")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product", "movement_type", "quantity", "business", "created_at")
    list_filter = ("movement_type", "business")


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "supplier", "business", "status", "created_at")
    list_filter = ("status", "business")
    inlines = [PurchaseOrderItemInline]
