import csv
from datetime import datetime
from django.core.management.base import BaseCommand
from wts_app.models.people import ParliamentaryAffiliation, Person
from wts_app.models.electorates import Electorate
from wts_app.models.parliaments import Parliament
from wts_app.models.gazette import GazetteNotice

CSV_FILE = "migration/parliamentary_affiliations.csv"

def parse_date(s):
    if not s or s.strip() == "":
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None

class Command(BaseCommand):
    help = "Migrate parliamentary affiliations from legacy CSV"

    def add_arguments(self, parser):
        parser.add_argument('--csv', type=str, default=CSV_FILE,
                            help="Path to CSV file to use (default: migration/parliamentary_affiliations.csv)")

    def handle(self, *args, **options):
        path = options['csv']
        with open(path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            created = 0
            skipped = 0
            for row in reader:
                legacy_id = row['legacy_id']
                if not legacy_id or legacy_id.strip() == "":
                    self.stdout.write(self.style.WARNING(f"Skipping empty row"))
                    skipped += 1
                    continue

                try:
                    legacy_id = int(legacy_id)
                except Exception:
                    self.stdout.write(self.style.WARNING(f"Skipping row with invalid legacy_id: {legacy_id}"))
                    skipped += 1
                    continue

                # Check for existing record
                exists = ParliamentaryAffiliation.objects.filter(legacy_id=legacy_id).exists()
                if exists:
                    self.stdout.write(f"ParliamentaryAffiliation with legacy_id={legacy_id} already exists, skipping.")
                    skipped += 1
                    continue

                # Foreign keys
                person = None
                if row["person_legacy_id"]:
                    try:
                        person = Person.objects.get(legacy_id=int(row["person_legacy_id"]))
                    except Person.DoesNotExist:
                        self.stdout.write(self.style.WARNING(
                            f"Could not find Person with legacy_id={row['person_legacy_id']} for affiliation {legacy_id}, skipping."))
                        skipped += 1
                        continue

                parliament = None
                if row["parliament_legacy_id"]:
                    try:
                        parliament = Parliament.objects.get(legacy_id=int(row["parliament_legacy_id"]))
                    except Parliament.DoesNotExist:
                        self.stdout.write(self.style.WARNING(
                            f"Could not find Parliament with legacy_id={row['parliament_legacy_id']} for affiliation {legacy_id}, skipping."))
                        skipped += 1
                        continue

                electorate = None
                if row["electorate_legacy_id"]:
                    try:
                        electorate = Electorate.objects.get(legacy_id=int(row["electorate_legacy_id"]))
                    except Electorate.DoesNotExist:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Could not find Electorate with legacy_id={row['electorate_legacy_id']} for affiliation {legacy_id}, continuing without it."))
                        electorate = None

                # Gazette notices (not required)
                gazette_elected = None
                if row.get("gazette_notice_election_number"):
                    gaz_no = row["gazette_notice_election_number"]
                    try:
                        gazette_elected = GazetteNotice.objects.get(number=gaz_no)
                    except GazetteNotice.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f"No GazetteNotice with number {gaz_no!r}"))

                gazette_vacated = None
                if row.get("gazette_notice_vacation_number"):
                    gaz_no = row["gazette_notice_vacation_number"]
                    try:
                        gazette_vacated = GazetteNotice.objects.get(number=gaz_no)
                    except GazetteNotice.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f"No GazetteNotice with number {gaz_no!r}"))

                # replaced affiliation
                replaced = None
                if row.get("replaced_legacy_id"):
                    try:
                        replaced = ParliamentaryAffiliation.objects.get(legacy_id=int(row["replaced_legacy_id"]))
                    except ParliamentaryAffiliation.DoesNotExist:
                        # Allow as None
                        replaced = None

                affiliation = ParliamentaryAffiliation(
                    legacy_id=legacy_id,
                    sworn_date=parse_date(row.get("sworn_date")),
                    end_date=parse_date(row.get("end_date")),
                    elected_date=parse_date(row.get("elected_date")),
                    parliament=parliament,
                    person=person,
                    electorate=electorate,
                    fallback_electorate_slug=row.get("fallback_electorate_slug") or None,
                    end_reason=row.get("end_reason") or None,
                    start_reason=row.get("start_reason") or None,
                    gazette_notice_election=gazette_elected,
                    gazette_notice_vacation=gazette_vacated,
                    replaced=replaced,
                )
                affiliation.save()
                created += 1

                self.stdout.write(self.style.SUCCESS(f"Created ParliamentaryAffiliation {affiliation.legacy_id} ({person})"))

            self.stdout.write(self.style.SUCCESS(
                f"Done. Created {created} ParliamentaryAffiliations, skipped {skipped}."))
