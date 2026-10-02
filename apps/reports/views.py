from decimal import Decimal

from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncYear
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Role
from apps.authentication.permissions import HasRole
from apps.sales.models import Sale, SaleItem
from apps.expenses.models import Expense
from apps.inventory.models import Product, Category
from apps.reports.utils import parse_date_range, as_csv, wants_csv

REPORT_ROLES = [Role.ACCOUNTANT, Role.ADMIN]

TRUNC_BY_PERIOD = {"daily": TruncDate, "weekly": TruncWeek, "monthly": TruncMonth, "yearly": TruncYear}


class BaseReportView(APIView):
    permission_classes = [HasRole.any_of(*REPORT_ROLES)]

    def business_sales(self, request, statuses=("completed", "partially_refunded")):
        start, end = parse_date_range(request)
        return (
            Sale.objects.filter(
                business_id=request.user.business_id,
                status__in=statuses,
                created_at__date__gte=start,
                created_at__date__lte=end,
            ),
            start,
            end,
        )

    def business_expenses(self, request):
        start, end = parse_date_range(request)
        return (
            Expense.objects.filter(
                business_id=request.user.business_id, expense_date__gte=start, expense_date__lte=end
            ),
            start,
            end,
        )


class SalesReportView(BaseReportView):
    """Daily/Weekly/Monthly/Yearly sales — the brief's core sales reports, one endpoint."""

    def get(self, request):
        sales, start, end = self.business_sales(request)
        period = request.query_params.get("period", "daily")
        trunc = TRUNC_BY_PERIOD.get(period, TruncDate)

        rows = (
            sales.annotate(period=trunc("created_at"))
            .values("period")
            .annotate(
                sales_count=Count("id"),
                gross_sales=Sum("subtotal"),
                discount_total=Sum("discount_amount"),
                tax_total=Sum("tax_amount"),
                total_amount=Sum("total_amount"),
            )
            .order_by("period")
        )
        results = [
            {
                "period": r["period"].isoformat() if hasattr(r["period"], "isoformat") else str(r["period"]),
                "sales_count": r["sales_count"],
                "gross_sales": float(r["gross_sales"] or 0),
                "discount_total": float(r["discount_total"] or 0),
                "tax_total": float(r["tax_total"] or 0),
                "total_amount": float(r["total_amount"] or 0),
            }
            for r in rows
        ]

        if wants_csv(request):
            return as_csv(
                "sales_report.csv",
                ["period", "sales_count", "gross_sales", "discount_total", "tax_total", "total_amount"],
                results,
            )
        return Response({"start": str(start), "end": str(end), "period": period, "results": results})


class ProfitLossReportView(BaseReportView):
    def get(self, request):
        sales, start, end = self.business_sales(request)
        expenses, _, _ = self.business_expenses(request)

        revenue = sales.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        cost_of_goods = (
            SaleItem.objects.filter(sale__in=sales).aggregate(
                t=Sum(ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DecimalField(max_digits=14, decimal_places=2)))
            )["t"]
            or Decimal("0")
        )
        gross_profit = revenue - cost_of_goods
        total_expenses = expenses.aggregate(t=Sum("amount"))["t"] or Decimal("0")
        net_profit = gross_profit - total_expenses

        expense_breakdown = list(
            expenses.values("category__name").annotate(total=Sum("amount")).order_by("-total")
        )

        payload = {
            "start": str(start),
            "end": str(end),
            "revenue": float(revenue),
            "cost_of_goods_sold": float(cost_of_goods),
            "gross_profit": float(gross_profit),
            "total_expenses": float(total_expenses),
            "net_profit": float(net_profit),
            "expense_breakdown": [
                {"category": e["category__name"] or "Uncategorized", "total": float(e["total"])}
                for e in expense_breakdown
            ],
        }

        if wants_csv(request):
            rows = [{"metric": k, "value": v} for k, v in payload.items() if k not in ("expense_breakdown",)]
            return as_csv("profit_loss.csv", ["metric", "value"], rows)
        return Response(payload)


class ExpenseReportView(BaseReportView):
    def get(self, request):
        expenses, start, end = self.business_expenses(request)
        rows = list(
            expenses.select_related("category", "recorded_by")
            .values("title", "category__name", "amount", "expense_date", "recorded_by__username")
            .order_by("-expense_date")
        )
        results = [
            {
                "title": r["title"],
                "category": r["category__name"] or "Uncategorized",
                "amount": float(r["amount"]),
                "expense_date": str(r["expense_date"]),
                "recorded_by": r["recorded_by__username"],
            }
            for r in rows
        ]
        if wants_csv(request):
            return as_csv("expense_report.csv", ["title", "category", "amount", "expense_date", "recorded_by"], results)
        return Response({"start": str(start), "end": str(end), "total": sum(r["amount"] for r in results), "results": results})


class InventoryReportView(BaseReportView):
    def get(self, request):
        business_id = request.user.business_id
        products = Product.objects.filter(business_id=business_id)

        by_category = (
            products.values("category__name")
            .annotate(
                product_count=Count("id"),
                stock_value=Sum(ExpressionWrapper(F("current_stock") * F("buying_price"), output_field=DecimalField(max_digits=16, decimal_places=2))),
            )
            .order_by("-stock_value")
        )

        payload = {
            "total_products": products.count(),
            "total_stock_value": float(
                products.aggregate(t=Sum(ExpressionWrapper(F("current_stock") * F("buying_price"), output_field=DecimalField(max_digits=16, decimal_places=2))))["t"] or 0
            ),
            "low_stock_count": products.filter(current_stock__lte=F("minimum_stock"), current_stock__gt=0).count(),
            "out_of_stock_count": products.filter(current_stock=0).count(),
            "by_category": [
                {
                    "category": c["category__name"] or "Uncategorized",
                    "product_count": c["product_count"],
                    "stock_value": float(c["stock_value"] or 0),
                }
                for c in by_category
            ],
        }

        if wants_csv(request):
            return as_csv("inventory_report.csv", ["category", "product_count", "stock_value"], payload["by_category"])
        return Response(payload)


class CashFlowReportView(BaseReportView):
    def get(self, request):
        sales, start, end = self.business_sales(request)
        expenses, _, _ = self.business_expenses(request)

        inflow_by_day = {
            r["day"]: float(r["t"]) for r in sales.annotate(day=TruncDate("created_at")).values("day").annotate(t=Sum("amount_paid"))
        }
        outflow_by_day = {
            r["expense_date"]: float(r["t"]) for r in expenses.values("expense_date").annotate(t=Sum("amount"))
        }

        all_days = sorted(set(inflow_by_day) | set(outflow_by_day))
        results = [
            {
                "date": str(day),
                "inflow": inflow_by_day.get(day, 0),
                "outflow": outflow_by_day.get(day, 0),
                "net": inflow_by_day.get(day, 0) - outflow_by_day.get(day, 0),
            }
            for day in all_days
        ]

        if wants_csv(request):
            return as_csv("cash_flow.csv", ["date", "inflow", "outflow", "net"], results)
        return Response({"start": str(start), "end": str(end), "results": results})


class TopCustomersReportView(BaseReportView):
    def get(self, request):
        sales, start, end = self.business_sales(request)
        limit = int(request.query_params.get("limit", 10))
        rows = (
            sales.exclude(customer__isnull=True)
            .values("customer__id", "customer__name")
            .annotate(orders=Count("id"), total_spent=Sum("total_amount"))
            .order_by("-total_spent")[:limit]
        )
        results = [
            {"customer": r["customer__name"], "orders": r["orders"], "total_spent": float(r["total_spent"])}
            for r in rows
        ]
        if wants_csv(request):
            return as_csv("top_customers.csv", ["customer", "orders", "total_spent"], results)
        return Response({"start": str(start), "end": str(end), "results": results})


class TopProductsReportView(BaseReportView):
    def get(self, request):
        sales, start, end = self.business_sales(request)
        limit = int(request.query_params.get("limit", 10))
        rows = (
            SaleItem.objects.filter(sale__in=sales)
            .values("product__id", "product__name")
            .annotate(units_sold=Sum("quantity"), revenue=Sum("line_total"))
            .order_by("-revenue")[:limit]
        )
        results = [
            {"product": r["product__name"], "units_sold": float(r["units_sold"]), "revenue": float(r["revenue"])}
            for r in rows
        ]
        if wants_csv(request):
            return as_csv("top_products.csv", ["product", "units_sold", "revenue"], results)
        return Response({"start": str(start), "end": str(end), "results": results})


class EmployeePerformanceReportView(BaseReportView):
    def get(self, request):
        sales, start, end = self.business_sales(request)
        rows = (
            sales.exclude(cashier__isnull=True)
            .values("cashier__id", "cashier__username")
            .annotate(sales_count=Count("id"), total_amount=Sum("total_amount"))
            .order_by("-total_amount")
        )
        results = [
            {"cashier": r["cashier__username"], "sales_count": r["sales_count"], "total_amount": float(r["total_amount"])}
            for r in rows
        ]
        if wants_csv(request):
            return as_csv("employee_performance.csv", ["cashier", "sales_count", "total_amount"], results)
        return Response({"start": str(start), "end": str(end), "results": results})


class TaxReportView(BaseReportView):
    def get(self, request):
        sales, start, end = self.business_sales(request)
        rows = (
            sales.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(tax_collected=Sum("tax_amount"), taxable_sales=Sum("total_amount"))
            .order_by("day")
        )
        results = [
            {"date": str(r["day"]), "taxable_sales": float(r["taxable_sales"]), "tax_collected": float(r["tax_collected"])}
            for r in rows
        ]
        total_tax = sum(r["tax_collected"] for r in results)
        if wants_csv(request):
            return as_csv("tax_report.csv", ["date", "taxable_sales", "tax_collected"], results)
        return Response({"start": str(start), "end": str(end), "total_tax_collected": total_tax, "results": results})
