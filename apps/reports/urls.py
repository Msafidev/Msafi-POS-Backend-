from django.urls import path
from apps.reports.views import (
    SalesReportView, ProfitLossReportView, ExpenseReportView, InventoryReportView,
    CashFlowReportView, TopCustomersReportView, TopProductsReportView,
    EmployeePerformanceReportView, TaxReportView,
)

urlpatterns = [
    path("sales/", SalesReportView.as_view(), name="report-sales"),
    path("profit-loss/", ProfitLossReportView.as_view(), name="report-profit-loss"),
    path("expenses/", ExpenseReportView.as_view(), name="report-expenses"),
    path("inventory/", InventoryReportView.as_view(), name="report-inventory"),
    path("cash-flow/", CashFlowReportView.as_view(), name="report-cash-flow"),
    path("top-customers/", TopCustomersReportView.as_view(), name="report-top-customers"),
    path("top-products/", TopProductsReportView.as_view(), name="report-top-products"),
    path("employee-performance/", EmployeePerformanceReportView.as_view(), name="report-employee-performance"),
    path("tax/", TaxReportView.as_view(), name="report-tax"),
]
