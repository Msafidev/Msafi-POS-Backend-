from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "apps.notifications"

    def ready(self):
        from apps.notifications import signals  # noqa: F401 — registers the receivers
