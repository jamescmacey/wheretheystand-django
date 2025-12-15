import csv
from datetime import datetime
from django.core.management.base import BaseCommand
from wts_app.models.people import MinisterialPortfolio, MinisterialAffiliation, Person

PORTFOLIOS_CSV = "migration/ministerial_portfolios.csv"
AFFILIATIONS_CSV = "migration/ministerial_affiliations.csv"

class Command(BaseCommand):
    help = "Migrate ministerial portfolios and affiliations from legacy CSV files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--portfolios",
            type=str,
            default=PORTFOLIOS_CSV,
            help="Path to ministerial portfolios CSV file (default: migration/ministerial_portfolios.csv)"
        )
        parser.add_argument(
            "--affiliations",
            type=str,
            default=AFFILIATIONS_CSV,
            help="Path to ministerial affiliations CSV file (default: migration/ministerial_affiliations.csv)"
        )

    def handle(self, *args, **options):
        # First migrate portfolios indexed by legacy_id
        portfolios_csv = options["portfolios"]
        affiliations_csv = options["affiliations"]

        portfolio_legacy_map = {}
        created_portfolios = 0
        skipped_portfolios = 0

        with open(portfolios_csv, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                legacy_id = row.get("legacy_id", "").strip()
                if not legacy_id:
                    self.stdout.write(self.style.WARNING("Skipping portfolio with empty legacy_id"))
                    skipped_portfolios += 1
                    continue
                try:
                    legacy_id_int = int(legacy_id)
                except Exception:
                    self.stdout.write(self.style.WARNING(f"Skipping portfolio with invalid legacy_id '{legacy_id}'"))
                    skipped_portfolios += 1
                    continue
                name = (row.get("name") or "").strip()
                slug = (row.get("slug") or "").strip()
                if not name:
                    self.stdout.write(self.style.WARNING(f"Skipping portfolio with empty name (legacy_id={legacy_id})"))
                    skipped_portfolios += 1
                    continue

                obj, created = MinisterialPortfolio.objects.get_or_create(
                    legacy_id=legacy_id_int,
                    defaults={
                        "name": name,
                        "slug": slug or None
                    }
                )
                if created:
                    created_portfolios += 1
                    self.stdout.write(self.style.SUCCESS(f"Created MinisterialPortfolio: {name} (legacy_id={legacy_id})"))
                else:
                    self.stdout.write(f"MinisterialPortfolio '{name}' (legacy_id={legacy_id}) already exists, mapping to it.")
                portfolio_legacy_map[legacy_id] = obj

        self.stdout.write(self.style.SUCCESS(
            f"Portfolios import done. Created {created_portfolios}, skipped {skipped_portfolios}."
        ))

        # Now import affiliations, looking up Person by legacy_id as well
        created_affiliations = 0
        skipped_affiliations = 0

        with open(affiliations_csv, newline='', encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                legacy_id = row.get("legacy_id", "").strip()
                if not legacy_id:
                    self.stdout.write(self.style.WARNING("Skipping affiliation with empty legacy_id"))
                    skipped_affiliations += 1
                    continue
                try:
                    legacy_id_int = int(legacy_id)
                except Exception:
                    self.stdout.write(self.style.WARNING(f"Skipping affiliation with invalid legacy_id '{legacy_id}'"))
                    skipped_affiliations += 1
                    continue

                if MinisterialAffiliation.objects.filter(legacy_id=legacy_id_int).exists():
                    self.stdout.write(f"Affiliation with legacy_id={legacy_id} already exists, skipping.")
                    skipped_affiliations += 1
                    continue

                person_legacy_id = row.get("person_legacy_id", "").strip()
                if not person_legacy_id:
                    self.stdout.write(self.style.WARNING(f"Skipping affiliation with empty person_legacy_id (legacy_id={legacy_id})"))
                    skipped_affiliations += 1
                    continue
                try:
                    person_obj = Person.objects.get(legacy_id=int(person_legacy_id))
                except Exception:
                    self.stdout.write(self.style.WARNING(f"Skipping affiliation: Could not find Person with legacy_id={person_legacy_id} (affiliation legacy_id={legacy_id})"))
                    skipped_affiliations += 1
                    continue

                portfolio_legacy_id = row.get("portfolio_legacy_id", "").strip()
                portfolio = None
                if not portfolio_legacy_id:
                    self.stdout.write(self.style.WARNING(f"Skipping affiliation with empty portfolio_legacy_id (legacy_id={legacy_id})"))
                    skipped_affiliations += 1
                    continue
                portfolio = portfolio_legacy_map.get(portfolio_legacy_id)
                if not portfolio:
                    try:
                        # Just in case, try DB for portfolios not seen in file
                        portfolio = MinisterialPortfolio.objects.get(legacy_id=int(portfolio_legacy_id))
                    except Exception:
                        self.stdout.write(self.style.WARNING(f"Skipping affiliation: Could not find Portfolio legacy_id={portfolio_legacy_id} (affiliation legacy_id={legacy_id})"))
                        skipped_affiliations += 1
                        continue

                start_date_str = row.get("start_date", "").strip()
                end_date_str = row.get("end_date", "").strip()
                try:
                    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
                except Exception as e:
                    self.stdout.write(self.style.WARNING(
                        f"Skipping affiliation: invalid start/end date (legacy_id={legacy_id}): {e}"
                    ))
                    skipped_affiliations += 1
                    continue

                title = (row.get("title") or "").strip() or None
                conjunction = (row.get("conjunction") or "").strip() or None
                appointment_method = (row.get("appointment_method") or "").strip() or None
                aff_type = (row.get("type") or "").strip() or "p"
                specialisation = (row.get("specialisation") or "").strip() or None

                obj = MinisterialAffiliation(
                    legacy_id=legacy_id_int,
                    person=person_obj,
                    portfolio=portfolio,
                    start_date=start_date,
                    end_date=end_date,
                    title=title,
                    conjunction=conjunction,
                    appointment_method=appointment_method,
                    type=aff_type,
                    specialisation=specialisation,
                )
                obj.save()
                created_affiliations += 1
                self.stdout.write(self.style.SUCCESS(
                    f"Created MinisterialAffiliation for {person_obj.display_name}: {portfolio.name} ({start_date} - {end_date})"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"Affiliations import done. Created {created_affiliations}, skipped {skipped_affiliations}."
        ))
