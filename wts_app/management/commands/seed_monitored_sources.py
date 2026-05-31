from django.core.management.base import BaseCommand

from wts_app.models import MonitoredSource


class Command(BaseCommand):
    help = "Seed default MonitoredSource rows for workbook automation."

    def handle(self, *args, **options):
        MonitoredSource.objects.update_or_create(
            slug="gazette_electoral_act",
            defaults={
                "name": "Gazette — Electoral Act",
                "handler": "gazette_electoral_act",
                "default_recipe_key": "gazette_notice",
                "config": {
                    "poll_days": 7,
                    "auto_advance": {"link_entities": True},
                },
                "is_active": False,
            },
        )
        self.stdout.write(self.style.SUCCESS("Monitored sources seeded (gazette inactive by default)."))
