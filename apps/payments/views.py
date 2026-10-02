from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.addons.permissions import HasActiveAddon
from apps.authentication.permissions import IsBusinessAdmin
from apps.payments.engine import PaymentEngine
from apps.payments.models import PaymentProvider, PaymentTransaction
from apps.payments.serializers import (
    ChargeRequestSerializer,
    ConfirmTerminalSerializer,
    PaymentProviderPublicSerializer,
    PaymentProviderSerializer,
    PaymentTransactionSerializer,
)
from apps.sales.models import Sale

PaymentsAddonRequired = HasActiveAddon.for_feature("payments")


class ActivePaymentProvidersView(APIView):
    """
    Cashier-safe list of this business's active payment providers (which
    banks/gateways are connected and what to call them) — no credential
    fields, unlike PaymentProviderViewSet which is admin-only because it
    also handles connecting/editing those credentials. Powers the
    "choose a bank" / "pay by M-Pesa" step in the POS checkout modal.
    """

    permission_classes = [permissions.IsAuthenticated, PaymentsAddonRequired]

    def get(self, request):
        providers = PaymentProvider.objects.filter(business=request.user.business, active=True)
        return Response(PaymentProviderPublicSerializer(providers, many=True).data)


class PaymentProviderViewSet(viewsets.ModelViewSet):
    """
    Where a business owner connects their own bank/PesaPal/M-Pesa
    account. Admin/Super Admin only — cashiers just see which providers
    are active when they take payment, never the credentials. Gated
    behind the "payments" add-on: connecting a provider is itself part
    of the paid feature, not just using it at checkout.
    """

    serializer_class = PaymentProviderSerializer
    permission_classes = [IsBusinessAdmin, PaymentsAddonRequired]

    def get_queryset(self):
        return PaymentProvider.objects.filter(business=self.request.user.business)


class PaymentTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only list/retrieve of gateway-side payment attempts, plus the
    action endpoints that actually move money: `initiate` (start a
    charge), `refresh` (poll the provider), and `confirm_terminal`
    (cashier keys in the PDQ terminal's approval code).
    """

    serializer_class = PaymentTransactionSerializer
    permission_classes = [permissions.IsAuthenticated, PaymentsAddonRequired]

    def get_queryset(self):
        return PaymentTransaction.objects.filter(business=self.request.user.business).select_related("provider")

    @action(detail=False, methods=["post"])
    def initiate(self, request):
        serializer = ChargeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        sale = None
        if data.get("sale_id"):
            sale = Sale.objects.filter(id=data["sale_id"], business=request.user.business).first()
            if sale is None:
                return Response({"detail": "Sale not found for this business."}, status=status.HTTP_404_NOT_FOUND)

        try:
            transaction = PaymentEngine.charge(
                business=request.user.business,
                provider_code=data["provider"],
                amount=data["amount"],
                sale=sale,
                phone_number=data.get("phone_number", ""),
                initiated_by=request.user,
            )
        except PaymentEngine.PaymentEngineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            PaymentTransactionSerializer(transaction).data,
            status=status.HTTP_202_ACCEPTED if transaction.status == "processing" else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        transaction = self.get_object()
        transaction = PaymentEngine.refresh_status(transaction)
        return Response(PaymentTransactionSerializer(transaction).data)

    @action(detail=True, methods=["post"], url_path="confirm-terminal")
    def confirm_terminal(self, request, pk=None):
        transaction = self.get_object()
        if transaction.status != PaymentTransaction.Status.AWAITING_TERMINAL:
            return Response({"detail": "This transaction isn't awaiting terminal confirmation."}, status=400)
        serializer = ConfirmTerminalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction.status = PaymentTransaction.Status.SUCCESS
        transaction.provider_reference = serializer.validated_data["provider_reference"]
        transaction.save()
        return Response(PaymentTransactionSerializer(transaction).data)


class MpesaCallbackView(APIView):
    """
    Public — Safaricom Daraja hits this directly, so no auth (there's no
    session/JWT for Safaricom's servers to send). Safety comes from the
    URL embedding the exact transaction UUID we generated when the STK
    push was sent, not from any shared secret in the payload itself.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, transaction_id):
        transaction = PaymentTransaction.objects.filter(id=transaction_id).first()
        if transaction is None:
            return Response({"ResultCode": 1, "ResultDesc": "Unknown transaction"}, status=404)
        PaymentEngine.apply_callback(transaction, request.data)
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


class PesapalCallbackView(APIView):
    """PesaPal's IPN is a GET with OrderTrackingId as a query param."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        tracking_id = request.query_params.get("OrderTrackingId", "")
        transaction = PaymentTransaction.objects.filter(checkout_request_id=tracking_id).first()
        if transaction is None:
            return Response({"detail": "Unknown transaction"}, status=404)
        # PesaPal's IPN doesn't carry a result code — re-poll the real status.
        PaymentEngine.refresh_status(transaction)
        return Response({"status": "ok"})
