from django.contrib.auth import get_user_model
from rest_framework import status, generics, permissions, viewsets, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.authentication.serializers import (
    LoginSerializer,
    RegisterBusinessSerializer,
    UserSerializer,
    UserManageSerializer,
    ActivityLogSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
)
from apps.authentication.models import ActivityLog, Role

User = get_user_model()


def _log(request, user, action, description=""):
    ActivityLog.objects.create(
        user=user,
        business=getattr(user, "business", None),
        action=action,
        description=description,
        ip_address=request.META.get("REMOTE_ADDR"),
    )


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            _log(request, serializer.user, "login")
        return response


class RegisterBusinessView(generics.CreateAPIView):
    """Public: sign up a new business (tenant) + its first admin user."""

    serializer_class = RegisterBusinessSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        _log(request, result["user"], "business.register", description=result["business"].name)
        return Response(
            {"business_id": str(result["business"].id), "user": UserSerializer(result["user"]).data},
            status=status.HTTP_201_CREATED,
        )


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserViewSet(viewsets.ModelViewSet):
    """
    Business-scoped staff management — the "Users" panel under Settings.
    Admins manage their own business's staff; Super Admins see everyone.
    A user can't deactivate or delete their own account through here.
    """

    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["role", "is_active", "branch"]
    search_fields = ["username", "email", "first_name", "last_name"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            from apps.authentication.permissions import IsBusinessAdmin
            return [IsBusinessAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.SUPER_ADMIN:
            return User.objects.all()
        return User.objects.filter(business_id=user.business_id)

    def get_serializer_class(self):
        return UserManageSerializer

    def perform_destroy(self, instance):
        if instance.id == self.request.user.id:
            raise serializers.ValidationError("You can't remove your own account.")
        instance.is_active = False
        instance.save(update_fields=["is_active"])


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only audit trail — the "Audit Logs" panel under Settings."""

    serializer_class = ActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["action", "user"]
    ordering_fields = ["created_at"]

    def get_queryset(self):
        user = self.request.user
        qs = ActivityLog.objects.select_related("user")
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(business_id=user.business_id)


class PasswordResetRequestView(generics.GenericAPIView):
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        if result:
            # TODO Phase 4: send via configured email backend / templates.
            # Kept as a no-op here so Phase 1 doesn't require SMTP creds.
            pass
        return Response({"detail": "If that email exists, a reset link has been sent."})


class PasswordResetConfirmView(generics.GenericAPIView):
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password has been reset. You can now log in."})
