from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.addons.permissions import HasActiveAddon
from apps.authentication.models import Role
from apps.authentication.permissions import HasRole, IsBusinessAdmin
from apps.reports.utils import parse_date_range
from apps.sales.models import Sale
from apps.tax import services
from apps.tax.etims import ETIMSAdapter, ETIMSAdapterError
from apps.tax.models import ETIMSInvoice, TaxProfile, TaxRecord
from apps.tax.serializers import (
    ETIMSInvoiceSerializer,
    EstimateTaxSerializer,
    TaxProfileSerializer,
    TaxRecordSerializer,
)

TaxAddonRequired = HasActiveAddon.for_feature("tax")
TAX_ROLES = [Role.ACCOUNTANT, Role.ADMIN]


class TaxProfileView(APIView):
    """Get-or-create-on-first-save view of this business's tax configuration."""

    permission_classes = [IsBusinessAdmin, TaxAddonRequired]

    def get(self, request):
        profile, _ = TaxProfile.objects.get_or_create(business=request.user.business)
        return Response(TaxProfileSerializer(profile).data)

    def patch(self, request):
        profile, _ = TaxProfile.objects.get_or_create(business=request.user.business)
        serializer = TaxProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(TaxProfileSerializer(profile).data)


class TaxRecordViewSet(viewsets.ModelViewSet):
    """
    Manual tax records (WHT/CGT/Excise/DST always; Turnover/Corporation
    Tax too, if the business wants to log its own figure instead of
    MsafiPOS's estimate). Use `estimate` for a MsafiPOS-computed figure
    on the two tax types that support one.
    """

    serializer_class = TaxRecordSerializer
    permission_classes = [HasRole.any_of(*TAX_ROLES), TaxAddonRequired]

    def get_queryset(self):
        qs = TaxRecord.objects.filter(business_id=self.request.user.business_id)
        tax_type = self.request.query_params.get("tax_type")
        if tax_type:
            qs = qs.filter(tax_type=tax_type)
        return qs

    @action(detail=False, methods=["post"])
    def estimate(self, request):
        serializer = EstimateTaxSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        profile, _ = TaxProfile.objects.get_or_create(business=request.user.business)
        rate_field = {"turnover_tax": "turnover_tax_rate", "corporation_tax": "corporation_tax_rate"}[data["tax_type"]]
        rate = getattr(profile, rate_field)
        if rate is None:
            return Response(
                {"detail": f"Set a rate for {data['tax_type']} in your tax profile first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount = services.estimate_tax(
            data["tax_type"], request.user.business, data["period_start"], data["period_end"], rate
        )
        record = TaxRecord.objects.create(
            business=request.user.business,
            tax_type=data["tax_type"],
            period_start=data["period_start"],
            period_end=data["period_end"],
            rate_used=rate,
            is_estimated=True,
            amount=amount,
            recorded_by=request.user,
            note="Estimated by MsafiPOS from sales data.",
        )
        return Response(TaxRecordSerializer(record).data, status=status.HTTP_201_CREATED)


class TaxSummaryView(APIView):
    """
    One screen's worth of "what do I owe" — turnover/gross-profit-based
    estimates for the tax types MsafiPOS can compute, plus each
    configured rate for the rest so the business remembers what to log
    manually. VAT is deliberately excluded here — it's free/base-tier and
    already visible via the Sales/Reports VAT figures and Business.vat_percent.
    """

    permission_classes = [HasRole.any_of(*TAX_ROLES), TaxAddonRequired]

    def get(self, request):
        start, end = parse_date_range(request)
        business = request.user.business
        profile, _ = TaxProfile.objects.get_or_create(business=business)

        rates = {
            "corporation_tax": profile.corporation_tax_rate,
            "turnover_tax": profile.turnover_tax_rate,
            "withholding_tax": profile.withholding_tax_rate,
            "capital_gains_tax": profile.capital_gains_tax_rate,
            "excise_duty": profile.excise_duty_rate,
            "digital_service_tax": profile.digital_service_tax_rate,
        }
        estimates = {
            tax_type: services.estimate_tax(tax_type, business, start, end, rate)
            for tax_type, rate in rates.items()
            if tax_type in services.ESTIMATABLE_TAX_TYPES
        }
        return Response(
            {
                "start": str(start),
                "end": str(end),
                "turnover": float(services.turnover(business, start, end)),
                "gross_profit": float(services.gross_profit(business, start, end)),
                "rates": {k: (float(v) if v is not None else None) for k, v in rates.items()},
                "estimates": {k: (float(v) if v is not None else None) for k, v in estimates.items()},
                "manual_entry_required": sorted(set(rates) - services.ESTIMATABLE_TAX_TYPES),
            }
        )


class ETIMSConnectionStatusView(APIView):
    """
    Powers the Connected / Not Connected badge on the Tax settings screen.
    Gated the same as the rest of eTIMS (tax add-on) but read-only and
    side-effect-free from the shop's point of view — it doesn't submit
    any invoice, just checks whether KRA's device init call succeeds.
    """

    permission_classes = [permissions.IsAuthenticated, HasActiveAddon.for_feature("tax")]

    def get(self, request):
        profile, _ = TaxProfile.objects.get_or_create(business=request.user.business)
        result = ETIMSAdapter(profile).check_connection()
        return Response(result)


class ETIMSInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ETIMSInvoiceSerializer

    def get_permissions(self):
        if self.action == "submit":
            return [HasRole.any_of(*TAX_ROLES)(), TaxAddonRequired()]
        # list/retrieve: any authenticated staff member needs this to show
        # the eTIMS invoice number/QR on a printed receipt, not just
        # accountants/admins.
        return [permissions.IsAuthenticated(), TaxAddonRequired()]

    def get_queryset(self):
        qs = ETIMSInvoice.objects.filter(business_id=self.request.user.business_id).select_related("sale")
        sale_id = self.request.query_params.get("sale")
        if sale_id:
            qs = qs.filter(sale_id=sale_id)
        return qs

    @action(detail=False, methods=["post"])
    def submit(self, request):
        sale_id = request.data.get("sale_id")
        sale = Sale.objects.filter(id=sale_id, business_id=request.user.business_id).first()
        if sale is None:
            return Response({"detail": "Sale not found for this business."}, status=status.HTTP_404_NOT_FOUND)

        profile, _ = TaxProfile.objects.get_or_create(business=request.user.business)
        invoice, _ = ETIMSInvoice.objects.get_or_create(business=request.user.business, sale=sale)

        if not profile.etims_enabled:
            invoice.status = ETIMSInvoice.Status.NOT_CONFIGURED
            invoice.failure_reason = "eTIMS isn't enabled for this business yet — set it up in Tax settings first."
            invoice.save()
            return Response(ETIMSInvoiceSerializer(invoice).data, status=status.HTTP_400_BAD_REQUEST)

        try:
            adapter = ETIMSAdapter(profile)
            response_data = adapter.submit_invoice(sale)
        except (ETIMSAdapterError, Exception) as exc:  # noqa: BLE001 — surface any adapter/network failure as a failed submission, not a 500
            invoice.status = ETIMSInvoice.Status.FAILED
            invoice.failure_reason = str(exc)
            invoice.save()
            return Response(ETIMSInvoiceSerializer(invoice).data, status=status.HTTP_502_BAD_GATEWAY)

        invoice.status = ETIMSInvoice.Status.SUBMITTED
        invoice.raw_response = response_data
        invoice.kra_invoice_number = str(response_data.get("invcNo", ""))
        invoice.qr_code_data = str(response_data.get("qrCode", ""))
        invoice.save()
        return Response(ETIMSInvoiceSerializer(invoice).data)
