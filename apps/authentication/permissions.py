from rest_framework.permissions import BasePermission

from apps.authentication.models import Role


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.SUPER_ADMIN)


class IsBusinessAdmin(BasePermission):
    """Admin or Super Admin."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (Role.SUPER_ADMIN, Role.ADMIN)
        )


class HasRole:
    """
    Factory for a permission class scoped to a set of roles, so views can
    declare access declaratively:

        permission_classes = [HasRole.any_of(Role.MANAGER, Role.ADMIN)]
    """

    @staticmethod
    def any_of(*roles):
        class _RolePermission(BasePermission):
            allowed_roles = roles

            def has_permission(self, request, view):
                return bool(
                    request.user
                    and request.user.is_authenticated
                    and (request.user.role in self.allowed_roles or request.user.role == Role.SUPER_ADMIN)
                )

        return _RolePermission


class BelongsToSameBusiness(BasePermission):
    """Object-level check: the object's `business` must match the requesting user's business."""

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.SUPER_ADMIN:
            return True
        obj_business = getattr(obj, "business", None)
        return bool(obj_business and obj_business == request.user.business)
