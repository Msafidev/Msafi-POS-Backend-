from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.payments.views import (
    ActivePaymentProvidersView,
    MpesaCallbackView,
    PaymentProviderViewSet,
    PaymentTransactionViewSet,
    PesapalCallbackView,
)

router = DefaultRouter()
router.register("providers", PaymentProviderViewSet, basename="payment-provider")
router.register("transactions", PaymentTransactionViewSet, basename="payment-transaction")

urlpatterns = [
    path("providers/active/", ActivePaymentProvidersView.as_view(), name="active-payment-providers"),
    path("mpesa/callback/<uuid:transaction_id>/", MpesaCallbackView.as_view(), name="mpesa-callback"),
    path("pesapal/callback/", PesapalCallbackView.as_view(), name="pesapal-callback"),
] + router.urls
