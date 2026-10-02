from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.inventory.models import Product
from apps.notifications.models import Notification


class Command(BaseCommand):
    """
    Expiring-product notifications are date-driven, not event-driven —
    nothing "happens" to trigger them the way a sale or stock movement
    does. Run this daily via cron / celery-beat / a scheduled task in
    whatever's hosting the backend:
        python manage.py check_expiring_products --days 7
    """

    help = "Creates EXPIRING_PRODUCT notifications for products expiring within --days (default 7)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **options):
        days = options["days"]
        today = timezone.localdate()
        cutoff = today + timedelta(days=days)
        qs = Product.objects.filter(expiry_date__isnull=False, expiry_date__gte=today, expiry_date__lte=cutoff)

        created = 0
        for product in qs:
            exists = Notification.objects.filter(
                business_id=product.business_id,
                type=Notification.Type.EXPIRING_PRODUCT,
                related_object_id=product.id,
                is_read=False,
            ).exists()
            if not exists:
                Notification.objects.create(
                    business_id=product.business_id,
                    type=Notification.Type.EXPIRING_PRODUCT,
                    title=f"{product.name} is expiring soon",
                    message=f"Expires on {product.expiry_date.isoformat()}.",
                    related_object_id=product.id,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} expiring-product notification(s)."))
