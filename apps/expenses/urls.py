from rest_framework.routers import DefaultRouter
from apps.expenses.views import ExpenseViewSet, ExpenseCategoryViewSet

router = DefaultRouter()
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("expense-categories", ExpenseCategoryViewSet, basename="expense-category")

urlpatterns = router.urls
