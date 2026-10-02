from rest_framework.routers import DefaultRouter
from apps.customers.views import CustomerViewSet, CustomerGroupViewSet, CustomerNoteViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("customer-groups", CustomerGroupViewSet, basename="customer-group")
router.register("customer-notes", CustomerNoteViewSet, basename="customer-note")

urlpatterns = router.urls
