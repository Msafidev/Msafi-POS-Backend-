from django.utils import timezone

from apps.addons.models import AddOnSubscription


def has_active_addon(business, feature):
    """
    The one function every gated feature (payments provider endpoints now,
    tax module later) calls to decide whether a business has paid for
    that add-on. Super Admins have no business and never hit this — they
    manage the platform, not a shop's own features.
    """
    if business is None:
        return False
    return AddOnSubscription.objects.filter(
        business=business, feature=feature, expires_at__gt=timezone.now()
    ).exists()
