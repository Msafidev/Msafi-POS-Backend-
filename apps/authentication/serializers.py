from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.businesses.models import Business, Branch
from apps.authentication.models import Role, ActivityLog

User = get_user_model()


class BusinessMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ["id", "name", "slug", "logo", "currency"]


class BranchMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "name", "code", "is_main"]


class UserSerializer(serializers.ModelSerializer):
    business = BusinessMiniSerializer(read_only=True)
    branch = BranchMiniSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "role", "phone", "avatar", "business", "branch",
            "is_email_verified", "must_change_password", "date_joined",
        ]
        read_only_fields = ["id", "role", "is_email_verified", "date_joined"]


class LoginSerializer(TokenObtainPairSerializer):
    """
    Adds role/business/branch context onto the JWT itself so the frontend
    can render permissions without an extra round trip, while /me/ remains
    the source of truth for the full profile.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["business_id"] = str(user.business_id) if user.business_id else None
        token["branch_id"] = str(user.branch_id) if user.branch_id else None
        token["full_name"] = user.get_full_name() or user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class RegisterBusinessSerializer(serializers.Serializer):
    """
    Onboarding: creates a new tenant (Business) plus its first Admin user
    and main Branch, in one transaction-safe call.
    """

    business_name = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("That email is already registered.")
        return value

    def create(self, validated_data):
        from django.utils.text import slugify
        from django.db import transaction
        from apps.authentication.models import Role

        with transaction.atomic():
            base_slug = slugify(validated_data["business_name"])
            slug = base_slug
            counter = 1
            while Business.objects.filter(slug=slug).exists():
                counter += 1
                slug = f"{base_slug}-{counter}"

            business = Business.objects.create(
                name=validated_data["business_name"],
                slug=slug,
            )
            branch = Branch.objects.create(business=business, name="Main Branch", code="MAIN", is_main=True)
            user = User.objects.create_user(
                username=validated_data["username"],
                email=validated_data["email"],
                password=validated_data["password"],
                business=business,
                branch=branch,
                role=Role.ADMIN,
            )
            return {"business": business, "user": user}


class UserManageSerializer(serializers.ModelSerializer):
    """
    Write-side shape for /users/ — how a business Admin adds and manages
    their own staff (cashiers, managers, store keepers, accountants).
    Deliberately separate from UserSerializer (the /me/ profile shape):
    this one accepts a password on create and restricts which roles can be
    assigned so a non-super-admin can't grant super_admin from here.
    """

    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name", "password",
            "role", "branch", "phone", "is_active", "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]

    def validate_role(self, value):
        if value == Role.SUPER_ADMIN:
            raise serializers.ValidationError("Super Admin accounts can't be created from here.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        password = validated_data.pop("password", None)
        user = User(business_id=request.user.business_id, **validated_data)
        user.set_password(password or User.objects.make_random_password())
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = ActivityLog
        fields = ["id", "user", "user_name", "business", "action", "description", "ip_address", "metadata", "created_at"]
        read_only_fields = fields


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self):
        try:
            user = User.objects.get(email=self.validated_data["email"])
        except User.DoesNotExist:
            return None  # Never reveal whether an email exists.
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        return {"uid": uid, "token": token, "user": user}


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate(self, attrs):
        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            raise serializers.ValidationError("Invalid reset link.")
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError("This reset link has expired or already been used.")
        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        return user
