from django.apps import AppConfig


class WtsAppConfig(AppConfig):
    name = 'wts_app'
    verbose_name = 'WhereTheyStand'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Registers the receiver that keeps the Firestore events document in
        # step with this database.
        from .firebase import signals  # noqa: F401
