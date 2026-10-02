from rest_framework.routers import DefaultRouter
from apps.businesses.views import BusinessViewSet, BranchViewSet

router = DefaultRouter()
router.register("businesses", BusinessViewSet, basename="business")
router.register("branches", BranchViewSet, basename="branch")

urlpatterns = router.urls
