from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.authentication.views import (
    LoginView,
    RegisterBusinessView,
    MeView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    UserViewSet,
    ActivityLogViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("activity-logs", ActivityLogViewSet, basename="activity-log")

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("register-business/", RegisterBusinessView.as_view(), name="auth-register-business"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    path("", include(router.urls)),
]
