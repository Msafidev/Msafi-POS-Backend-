from django.conf import settings
from rest_framework import permissions, status as http_status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.addons import mpesa
from apps.addons.models import AddOnPayment, AddOnSubscription
from apps.addons.plans import ADDON_FEATURES
from apps.addons.serializers import (
    AddOnPaymentSerializer,
    InitiateSTKSerializer,
    RejectAddOnPaymentSerializer,
    VerifyAddOnPaymentSerializer,
    activate_addon,
)
from apps.authentication.models import Role
from apps.authentication.permissions import IsSuperAdmin


class AddOnPlansView(APIView):
    """Public pricing for the add-ons — paid via M-Pesa STK Push, auto-verified."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"addons": ADDON_FEATURES})


class MyAddonsView(APIView):
    """
    What the logged-in business currently has active, so the frontend can
    show a paywall banner instead of guessing from a 403. Keyed by
    feature -> {active, expires_at}.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if request.user.business_id is None:
            return Response({})
        rows = AddOnSubscription.objects.filter(business=request.user.business)
        by_feature = {row.feature: row for row in rows}
        return Response(
            {
                feature: {
                    "active": by_feature[feature].is_active
                    if feature in by_feature
                    else False,
                    "expires_at": by_feature[feature].expires_at
                    if feature in by_feature
                    else None,
                }
                for feature in ADDON_FEATURES
            }
        )


class InitiateAddOnPaymentView(APIView):
    """
    Starts the auto-verified purchase flow: sends an STK push to the
    shop's phone. The frontend then polls AddOnPaymentStatusView (or
    waits for Safaricom's callback to land) until it flips to verified.
    No Super Admin step in this path.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.business_id is None:
            return Response(
                {"detail": "Super Admins have no business to buy add-ons for."},
                status=400,
            )

        serializer = InitiateSTKSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feature = serializer.validated_data["feature"]
        phone_number = serializer.validated_data["phone_number"]
        # Daraja wants 2547XXXXXXXX, not 07XXXXXXXX.
        normalized_phone = "254" + phone_number[-9:]

        payment = AddOnPayment.objects.create(
            business=request.user.business,
            feature=feature,
            amount=ADDON_FEATURES[feature]["price"],
            payment_method=AddOnPayment.Method.STK_PUSH,
            payer_phone=normalized_phone,
            submitted_by=request.user,
            status=AddOnPayment.Status.PENDING,
        )

        callback_base = getattr(settings, "PUBLIC_API_BASE_URL", "").rstrip("/")
        try:
            merchant_request_id, checkout_request_id = mpesa.stk_push(
                phone_number=normalized_phone,
                amount=payment.amount,
                account_reference=f"MsafiPOS-{feature}",
                transaction_desc=ADDON_FEATURES[feature]["label"],
                callback_url=f"{callback_base}/api/v1/addons/mpesa/callback/",
            )
        except mpesa.STKError as exc:
            import traceback

            traceback.print_exc()

            print("\n" + "=" * 80)
            print("STK PUSH ERROR")
            print(str(exc))
            print("=" * 80)

            payment.status = AddOnPayment.Status.FAILED
            payment.rejection_reason = str(exc)
            payment.save(update_fields=["status", "rejection_reason"])

            return Response(
                {
                    "detail": str(exc),
                },
                status=502,
            )

        payment.checkout_request_id = checkout_request_id
        payment.merchant_request_id = merchant_request_id
        payment.status = AddOnPayment.Status.PROCESSING
        payment.save(
            update_fields=["checkout_request_id", "merchant_request_id", "status"]
        )
        return Response(AddOnPaymentSerializer(payment).data, status=201)


class AddOnPaymentStatusView(APIView):
    """
    Polled by the frontend after InitiateAddOnPaymentView while the user
    has the STK prompt on their phone. Falls back to an active Daraja
    query in case Safaricom's async callback hasn't arrived yet.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        try:
            payment = AddOnPayment.objects.get(
                pk=pk, business_id=request.user.business_id
            )
        except AddOnPayment.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)

        if (
            payment.status == AddOnPayment.Status.PROCESSING
            and payment.checkout_request_id
        ):
            result, message = mpesa.query_status(payment.checkout_request_id)
            if result == "success":
                if payment.status != AddOnPayment.Status.VERIFIED:
                    activate_addon(payment)
            elif result == "failed":
                payment.status = AddOnPayment.Status.FAILED
                payment.rejection_reason = message
                payment.save(update_fields=["status", "rejection_reason"])

        return Response(AddOnPaymentSerializer(payment).data)


class MpesaAddonCallbackView(APIView):
    """Public webhook Safaricom calls once the customer completes (or cancels) the STK prompt."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        result = mpesa.parse_callback(request.data)
        try:
            payment = AddOnPayment.objects.get(
                checkout_request_id=result["checkout_request_id"]
            )
        except AddOnPayment.DoesNotExist:
            # Still 200 — Safaricom retries on non-2xx, and there's nothing more we can do here.
            return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

        if payment.status in (AddOnPayment.Status.VERIFIED, AddOnPayment.Status.FAILED):
            return Response({"ResultCode": 0, "ResultDesc": "Already processed"})

        if result["status"] == "success":
            payment.transaction_code = result["receipt_number"]
            payment.save(update_fields=["transaction_code"])
            activate_addon(payment)
        else:
            payment.status = AddOnPayment.Status.FAILED
            payment.rejection_reason = result["message"]
            payment.save(update_fields=["status", "rejection_reason"])

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


class AddOnPaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """History list + manual verify/reject fallback. Creation happens via InitiateAddOnPaymentView."""

    serializer_class = AddOnPaymentSerializer

    def get_permissions(self):
        if self.action in ("verify", "reject"):
            return [IsSuperAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = AddOnPayment.objects.select_related(
            "business", "submitted_by", "verified_by"
        )
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(business_id=user.business_id)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        payment = self.get_object()
        if payment.status in (
            AddOnPayment.Status.VERIFIED,
            AddOnPayment.Status.REJECTED,
        ):
            return Response(
                {"detail": "This payment has already been reviewed."}, status=400
            )
        serializer = VerifyAddOnPaymentSerializer(
            data={}, context={"request": request, "payment": payment}
        )
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        return Response(AddOnPaymentSerializer(payment).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        payment = self.get_object()
        if payment.status in (
            AddOnPayment.Status.VERIFIED,
            AddOnPayment.Status.REJECTED,
        ):
            return Response(
                {"detail": "This payment has already been reviewed."}, status=400
            )
        serializer = RejectAddOnPaymentSerializer(
            data=request.data, context={"request": request, "payment": payment}
        )
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        return Response(AddOnPaymentSerializer(payment).data)
