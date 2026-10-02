from apps.authentication.models import Role


def validate_same_tenant(request, **fields):
    """
    Guards against a class of bug found while writing Phase 5 tests: a
    ModelSerializer's auto-generated PrimaryKeyRelatedField defaults to
    `Model.objects.all()` for its queryset — DRF only checks that the PK
    exists, never that it belongs to the caller's business. Without this,
    an authenticated user in Business A could pass a Business B category/
    supplier/product UUID and DRF would happily accept it, silently
    associating (or in the Sales case, financially affecting) another
    tenant's data. Call this from `validate()` on any serializer that
    accepts a related-object PK the client controls, passing the field
    name and its validated value: `validate_same_tenant(request,
    category=attrs.get("category"), supplier=attrs.get("supplier"))`.
    Super Admins are exempt since they legitimately operate across tenants.
    """
    if request.user.role == Role.SUPER_ADMIN:
        return
    business_id = request.user.business_id
    for field_name, value in fields.items():
        if value is not None and getattr(value, "business_id", None) != business_id:
            from rest_framework import serializers

            raise serializers.ValidationError({field_name: "Invalid selection."})


class BusinessScopedQuerysetMixin:
    """
    Shared tenant-scoping logic for every Phase 2+ ViewSet. Super Admins see
    everything (support/ops access); everyone else only ever sees rows that
    belong to their own business — this is the entire multi-tenancy
    enforcement boundary on the shared-schema approach, so it lives in one
    place rather than being re-implemented per view.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(business_id=user.business_id)

    def perform_create(self, serializer):
        serializer.save(business_id=self.request.user.business_id)
