from rest_framework.routers import DefaultRouter
from apps.inventory.views import (
    CategoryViewSet, BrandViewSet, ProductViewSet, ProductVariantViewSet,
    ProductSerialNumberViewSet, StockMovementViewSet, PurchaseOrderViewSet,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("brands", BrandViewSet, basename="brand")
router.register("products", ProductViewSet, basename="product")
router.register("product-variants", ProductVariantViewSet, basename="product-variant")
router.register("product-serial-numbers", ProductSerialNumberViewSet, basename="product-serial-number")
router.register("stock-movements", StockMovementViewSet, basename="stock-movement")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")

urlpatterns = router.urls
