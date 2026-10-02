from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.addons.views import (
    AddOnPaymentStatusView,
    AddOnPaymentViewSet,
    AddOnPlansView,
    InitiateAddOnPaymentView,
    MpesaAddonCallbackView,
    MyAddonsView,
)

router = DefaultRouter()
router.register("payments", AddOnPaymentViewSet, basename="addon-payment")

urlpatterns = [
    path("plans/", AddOnPlansView.as_view(), name="addon-plans"),
    path("mine/", MyAddonsView.as_view(), name="my-addons"),
    path("stk/initiate/", InitiateAddOnPaymentView.as_view(), name="addon-stk-initiate"),
    path("stk/status/<uuid:pk>/", AddOnPaymentStatusView.as_view(), name="addon-stk-status"),
    path("mpesa/callback/", MpesaAddonCallbackView.as_view(), name="addon-mpesa-callback"),
] + router.urls
