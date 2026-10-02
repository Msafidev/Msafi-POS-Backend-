from django.contrib import admin
from apps.businesses.models import Business, Branch


class BranchInline(admin.TabularInline):
    model = Branch
    extra = 0


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    inlines = [BranchInline]


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "code", "is_main", "is_active")
    list_filter = ("business", "is_main")
