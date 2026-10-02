"""
What MsafiPOS can and can't compute for itself:

- Turnover Tax is legally just a flat rate on gross turnover (for
  qualifying small businesses), so `turnover(business, start, end)` ×
  the configured rate is a faithful figure.
- Corporation Tax is legally charged on taxable INCOME (revenue minus
  allowable deductions, capital allowances, etc.), which a POS system
  has no way to compute exactly. What we CAN compute is gross profit
  (revenue − cost of goods sold, same formula apps.reports.
  ProfitLossReportView already uses) — so the "Corporation Tax" figure
  here is explicitly labelled an ESTIMATE off gross profit, not a
  filing-ready number.
- Withholding Tax, Capital Gains Tax, Excise Duty, and Digital Service
  Tax all depend on facts outside of retail sales data (payments made TO
  suppliers, sale of a capital asset, which specific excisable goods,
  digital service revenue specifically) — MsafiPOS has no source of
  truth for any of these, so they are manual-entry only. The rate is
  still stored on TaxProfile so it's remembered next period.
"""

from decimal import Decimal

from django.db.models import Sum, F, ExpressionWrapper, DecimalField

from apps.sales.models import Sale, SaleItem

ESTIMATABLE_TAX_TYPES = {"turnover_tax", "corporation_tax"}


def turnover(business, start, end):
    return (
        Sale.objects.filter(
            business=business,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
            created_at__date__gte=start,
            created_at__date__lte=end,
        ).aggregate(t=Sum("total_amount"))["t"]
        or Decimal("0")
    )


def gross_profit(business, start, end):
    sales = Sale.objects.filter(
        business=business,
        status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
        created_at__date__gte=start,
        created_at__date__lte=end,
    )
    revenue = sales.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
    cost_of_goods = (
        SaleItem.objects.filter(sale__in=sales).aggregate(
            t=Sum(ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DecimalField(max_digits=14, decimal_places=2)))
        )["t"]
        or Decimal("0")
    )
    return revenue - cost_of_goods


def vat_collected(business, start, end):
    """The one tax figure that's always free — see apps.businesses.Business.vat_percent."""
    return (
        Sale.objects.filter(
            business=business,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
            created_at__date__gte=start,
            created_at__date__lte=end,
        ).aggregate(t=Sum("tax_amount"))["t"]
        or Decimal("0")
    )


def estimate_tax(tax_type, business, start, end, rate):
    """
    Returns a Decimal estimate for tax_type, or None if it can't be
    computed from POS data alone (caller should prompt for manual entry
    instead — see TaxRecord.is_estimated).
    """
    if rate is None:
        return None
    rate = Decimal(rate)
    if tax_type == "turnover_tax":
        return (turnover(business, start, end) * rate / Decimal(100)).quantize(Decimal("0.01"))
    if tax_type == "corporation_tax":
        profit = gross_profit(business, start, end)
        if profit <= 0:
            return Decimal("0.00")
        return (profit * rate / Decimal(100)).quantize(Decimal("0.01"))
    return None
