from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.tax.views import ETIMSConnectionStatusView, ETIMSInvoiceViewSet, TaxProfileView, TaxRecordViewSet, TaxSummaryView

router = DefaultRouter()
router.register("records", TaxRecordViewSet, basename="tax-record")
router.register("etims-invoices", ETIMSInvoiceViewSet, basename="etims-invoice")

urlpatterns = [
    path("profile/", TaxProfileView.as_view(), name="tax-profile"),
    path("summary/", TaxSummaryView.as_view(), name="tax-summary"),
    path("etims/status/", ETIMSConnectionStatusView.as_view(), name="etims-status"),
] + router.urls
