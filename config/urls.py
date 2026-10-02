from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.authentication.urls")),
    path("api/v1/", include("apps.businesses.urls")),
    path("api/v1/dashboard/", include("apps.dashboard.urls")),
    path("api/v1/", include("apps.suppliers.urls")),
    path("api/v1/", include("apps.customers.urls")),
    path("api/v1/", include("apps.inventory.urls")),
    path("api/v1/", include("apps.sales.urls")),
    path("api/v1/", include("apps.expenses.urls")),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/reports/", include("apps.reports.urls")),
    path("api/v1/payments/", include("apps.payments.urls")),
    path("api/v1/addons/", include("apps.addons.urls")),
    path("api/v1/tax/", include("apps.tax.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
