from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.addons.services import has_active_addon


class HasActiveAddon:
    """
    Factory for a permission class scoped to one add-on feature, so a
    ViewSet declares it the same way IsBusinessAdmin/HasRole are declared
    elsewhere in this codebase:

        permission_classes = [permissions.IsAuthenticated, HasActiveAddon.for_feature("payments")]

    Super Admins are never gated (there's no business to check), matching
    how every other business-scoping permission in this codebase treats
    them — they administer the platform, not one shop's paid features.
    """

    @staticmethod
    def for_feature(feature):
        class _AddonPermission(BasePermission):
            message = (
                f"This requires the '{feature}' add-on. Purchase it under "
                f"Settings to unlock this feature."
            )

            def has_permission(self, request, view):
                user = request.user
                if not (user and user.is_authenticated):
                    return False
                if user.business_id is None:  # Super Admin
                    return True
                if not has_active_addon(user.business, feature):
                    raise PermissionDenied(detail=self.message, code="addon_required")
                return True

        return _AddonPermission
