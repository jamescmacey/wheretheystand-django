from django.core.management.base import BaseCommand
from wts_app.models import GazetteNotice

class Command(BaseCommand):
    help = 'Creates gazette notice with the specified number.'

    def add_arguments(self, parser):
        parser.add_argument(
            'numbers',
            nargs='+',
            type=str,
            help='One or more gazette notice numbers to create.'
        )

    def handle(self, *args, **options):
        numbers = options['numbers']
        count_created = 0

        for number in numbers:
            obj, created = GazetteNotice.objects.get_or_create(number=number)
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created GazetteNotice: {number}"))
                count_created += 1
            else:
                self.stdout.write(f"GazetteNotice already exists: {number}")

        self.stdout.write(self.style.SUCCESS(f"Done. Created {count_created} gazette notices."))


