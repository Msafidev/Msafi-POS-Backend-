from rest_framework.routers import DefaultRouter
from apps.suppliers.views import SupplierViewSet, SupplierInvoiceViewSet

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("supplier-invoices", SupplierInvoiceViewSet, basename="supplier-invoice")

urlpatterns = router.urls
