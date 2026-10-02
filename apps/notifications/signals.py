from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.inventory.models import Product, PurchaseOrder
from apps.notifications.models import Notification


def _create_if_new(business_id, type_, title, message, related_object_id):
    """
    De-dupes on (business, type, related_object) while an existing
    notification of that kind is still unread — so a product sitting at
    low stock doesn't spam a fresh notification on every single sale that
    touches it, but a genuinely new event (e.g. it later goes fully out of
    stock) still gets its own alert since that's a different type.
    """
    exists = Notification.objects.filter(
        business_id=business_id, type=type_, related_object_id=related_object_id, is_read=False
    ).exists()
    if not exists:
        Notification.objects.create(
            business_id=business_id, type=type_, title=title, message=message, related_object_id=related_object_id
        )


@receiver(post_save, sender=Product)
def notify_stock_levels(sender, instance, created, **kwargs):
    if created:
        return  # a brand-new product isn't a stock *event* yet
    if instance.current_stock <= 0:
        _create_if_new(
            instance.business_id,
            Notification.Type.OUT_OF_STOCK,
            f"{instance.name} is out of stock",
            f"SKU {instance.sku} has 0 units remaining.",
            instance.id,
        )
    elif instance.current_stock <= instance.minimum_stock:
        _create_if_new(
            instance.business_id,
            Notification.Type.LOW_STOCK,
            f"{instance.name} is low on stock",
            f"{instance.current_stock} {instance.unit} left (minimum {instance.minimum_stock}).",
            instance.id,
        )


@receiver(post_save, sender=PurchaseOrder)
def notify_new_purchase_order(sender, instance, created, **kwargs):
    if created:
        _create_if_new(
            instance.business_id,
            Notification.Type.NEW_ORDER,
            f"New purchase order {instance.reference}",
            f"Ordered from {instance.supplier.name}.",
            instance.id,
        )
