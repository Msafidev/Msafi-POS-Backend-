from rest_framework.routers import DefaultRouter
from apps.sales.views import SaleViewSet, RefundViewSet

router = DefaultRouter()
router.register("sales", SaleViewSet, basename="sale")
router.register("refunds", RefundViewSet, basename="refund")

urlpatterns = router.urls
