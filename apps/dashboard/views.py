from datetime import timedelta

from django.db.models import Sum, F, Count, DecimalField, ExpressionWrapper
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.models import Sale, SaleItem
from apps.inventory.models import Product
from apps.tax.models import ETIMSInvoice, TaxProfile


class DashboardSummaryView(APIView):
    """
    Phase 3: real numbers, sourced from Sale/SaleItem/Product for the
    requesting user's business. `expenses` stays 0 until the Expenses app
    lands in Phase 4 — everything else here is live.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        business_id = request.user.business_id
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        completed = Sale.objects.filter(business_id=business_id, status__in=["completed", "partially_refunded"])

        def total_between(start, end=None):
            qs = completed.filter(created_at__date__gte=start)
            if end:
                qs = qs.filter(created_at__date__lte=end)
            return qs.aggregate(t=Sum("total_amount"))["t"] or 0

        today_sales = total_between(today, today)
        weekly_sales = total_between(week_start)
        monthly_sales = total_between(month_start)
        revenue = monthly_sales

        cost_of_goods = (
            SaleItem.objects.filter(sale__business_id=business_id, sale__created_at__date__gte=month_start)
            .aggregate(
                t=Sum(
                    ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DecimalField(max_digits=14, decimal_places=2))
                )
            )["t"]
            or 0
        )
        expenses = 0  # Phase 4
        profit = float(revenue) - float(cost_of_goods) - expenses

        top_products = (
            SaleItem.objects.filter(sale__business_id=business_id, sale__created_at__date__gte=month_start)
            .values("product__id", "product__name")
            .annotate(units_sold=Sum("quantity"), revenue=Sum("line_total"))
            .order_by("-units_sold")[:5]
        )

        low_stock_qs = Product.objects.filter(business_id=business_id, current_stock__lte=F("minimum_stock"))[:10]

        recent = completed.select_related("customer", "cashier").order_by("-created_at")[:10]

        etims_summary = None
        tax_profile = TaxProfile.objects.filter(business_id=business_id).first()
        if tax_profile and tax_profile.etims_enabled:
            todays_invoices = ETIMSInvoice.objects.filter(business_id=business_id, created_at__date=today)
            counts = {row["status"]: row["n"] for row in todays_invoices.values("status").annotate(n=Count("id"))}
            etims_summary = {
                "enabled": True,
                "environment": tax_profile.etims_environment,
                "submitted_today": counts.get(ETIMSInvoice.Status.SUBMITTED, 0),
                "pending_today": counts.get(ETIMSInvoice.Status.PENDING, 0),
                "failed_today": counts.get(ETIMSInvoice.Status.FAILED, 0),
            }
        else:
            etims_summary = {"enabled": False}

        def daily_series(field):
            rows = (
                completed.filter(created_at__date__gte=today - timedelta(days=6))
                .annotate(day=TruncDate("created_at"))
                .values("day")
                .annotate(total=Sum(field))
            )
            by_day = {r["day"].isoformat(): float(r["total"]) for r in rows}
            return [
                {"date": str(today - timedelta(days=i)), field: by_day.get(str(today - timedelta(days=i)), 0)}
                for i in range(6, -1, -1)
            ]

        return Response(
            {
                "today_sales": today_sales,
                "weekly_sales": weekly_sales,
                "monthly_sales": monthly_sales,
                "revenue": revenue,
                "profit": round(profit, 2),
                "expenses": expenses,
                "top_selling_products": [
                    {"id": str(p["product__id"]), "name": p["product__name"], "units_sold": float(p["units_sold"]), "revenue": float(p["revenue"])}
                    for p in top_products
                ],
                "low_stock_products": [
                    {"id": str(p.id), "name": p.name, "current_stock": float(p.current_stock), "minimum_stock": float(p.minimum_stock)}
                    for p in low_stock_qs
                ],
                "recent_transactions": [
                    {
                        "id": str(s.id),
                        "sale_number": s.sale_number,
                        "customer": s.customer.name if s.customer else "Walk-in",
                        "cashier": s.cashier.username if s.cashier else None,
                        "total_amount": float(s.total_amount),
                        "created_at": s.created_at.isoformat(),
                    }
                    for s in recent
                ],
                "sales_graph": [
                    {"date": d["date"], "sales": d["total_amount"]} for d in daily_series("total_amount")
                ],
                "etims_summary": etims_summary,
                "inventory_summary": {
                    "total_products": Product.objects.filter(business_id=business_id).count(),
                    "total_stock_value": float(
                        Product.objects.filter(business_id=business_id)
                        .aggregate(
                            t=Sum(
                                ExpressionWrapper(
                                    F("current_stock") * F("buying_price"),
                                    output_field=DecimalField(max_digits=16, decimal_places=2),
                                )
                            )
                        )["t"]
                        or 0
                    ),
                    "out_of_stock": Product.objects.filter(business_id=business_id, current_stock=0).count(),
                },
            }
        )
