from django.contrib import admin
from apps.expenses.models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "is_active")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "business", "category", "amount", "expense_date", "is_recurring")
    list_filter = ("business", "category", "is_recurring")
