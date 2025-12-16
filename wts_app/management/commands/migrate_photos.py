import csv
import os
import mimetypes
import urllib.request
import urllib.error
from django.core.management.base import BaseCommand, CommandError
from django.core.files.base import ContentFile
from django.utils import timezone
from django.conf import settings
from wts_app.models.people import Person
from wts_app.models.documents import File, Licence, CopyrightParty

CSV_FILE = "migration/photos_migration.csv"
BASE_URL = "https://storage.googleapis.com/wheretheystand-nz/"


class Command(BaseCommand):
    help = "Migrate person photos from CSV, downloading images from Google Cloud Storage"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default=CSV_FILE,
            help=f"Path to CSV file (default: {CSV_FILE})",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            default=BASE_URL,
            help=f"Base URL for images (default: {BASE_URL})",
        )

    def handle(self, *args, **options):
        csv_path = options["csv"]
        base_url = options["base_url"]

        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        processed = 0
        created = 0
        skipped = 0
        errors = 0

        with open(csv_path, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                # Try to get legacy_id, handling potential whitespace in column names
                legacy_id_str = None
                for key in row.keys():
                    if key.strip().lower() == "legacy_id":
                        legacy_id_str = row[key].strip() if row[key] else ""
                        break
                
                # Fallback to direct access if the above didn't work
                if legacy_id_str is None:
                    legacy_id_str = row.get("legacy_id", "").strip()
                
                if not legacy_id_str:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping row {row_num}: legacy_id is empty"
                        )
                    )
                    continue

                try:
                    legacy_id = int(legacy_id_str)
                except ValueError:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping row: invalid legacy_id '{legacy_id_str}' (not a number)"
                        )
                    )
                    continue

                picture_url = row.get("picture_url", "").strip()
                picture_attrib_text = row.get("picture_attrib_text", "").strip()
                original_url = row.get("original_url", "").strip()
                licence_name = row.get("licence", "").strip()
                licence_grantor_name = row.get("licence_grantor", "").strip()
                copyright_owner_name = row.get("copyright_owner", "").strip()

                # Skip if no picture URL
                if not picture_url:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping legacy_id={legacy_id}: picture_url is empty"
                        )
                    )
                    continue

                # Find the person
                try:
                    person = Person.objects.get(legacy_id=legacy_id)
                    display_name = person.display_name
                except Person.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Person with legacy_id={legacy_id} not found"
                        )
                    )
                    errors += 1
                    continue

                # Skip if person already has a photo
                if person.photo:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping {display_name} (legacy_id={legacy_id}): person already has a photo"
                        )
                    )
                    continue

                # Download the image
                image_url = base_url.rstrip("/") + "/" + picture_url.lstrip("/")
                try:
                    req = urllib.request.Request(image_url)
                    user_agent = getattr(settings, "BOT_USER_AGENT", "Mozilla/5.0")
                    req.add_header("User-Agent", user_agent)

                    with urllib.request.urlopen(req, timeout=30) as response:
                        image_content = response.read()
                        content_type = response.headers.get("Content-Type", "")

                    if not image_content:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Empty response for {display_name} (legacy_id={legacy_id})"
                            )
                        )
                        errors += 1
                        continue

                except (urllib.error.HTTPError, urllib.error.URLError) as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error downloading image for {display_name} (legacy_id={legacy_id}): {e}"
                        )
                    )
                    errors += 1
                    continue
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Unexpected error downloading image for {display_name} (legacy_id={legacy_id}): {e}"
                        )
                    )
                    errors += 1
                    continue

                # Determine file type from extension or content type
                filename = os.path.basename(picture_url)
                file_type, _ = mimetypes.guess_type(filename)
                if not file_type:
                    # Fallback to content type from response
                    if content_type:
                        file_type = content_type
                    else:
                        # Default based on extension
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in [".jpg", ".jpeg"]:
                            file_type = "image/jpeg"
                        elif ext == ".png":
                            file_type = "image/png"
                        elif ext == ".gif":
                            file_type = "image/gif"
                        elif ext == ".webp":
                            file_type = "image/webp"
                        else:
                            file_type = "image/jpeg"  # Default fallback

                # Create source URL - use original_url if available, otherwise use the Google Cloud Storage URL
                source_url = original_url if original_url else image_url

                # Get or create Licence, CopyrightParty objects
                licence = None
                if licence_name:
                    licence, _ = Licence.objects.get_or_create(name=licence_name)

                licence_grantor = None
                if licence_grantor_name:
                    licence_grantor, _ = CopyrightParty.objects.get_or_create(
                        name=licence_grantor_name
                    )

                copyright_owner = None
                if copyright_owner_name:
                    copyright_owner, _ = CopyrightParty.objects.get_or_create(
                        name=copyright_owner_name
                    )

                # Create File object
                try:
                    file_obj = File(
                        file_name=f"{display_name}'s photo",
                        file_description=picture_attrib_text if picture_attrib_text else None,
                        source_url=source_url if source_url else None,
                        file_type=file_type,
                        original_link_alive=True,
                        original_link_last_checked=timezone.now(),
                        licence=licence,
                        licence_grantor=licence_grantor,
                        copyright_owner=copyright_owner,
                    )

                    # Store the content temporarily so upload_to can access it for hashing
                    file_obj._file_content_for_hash = image_content

                    # Save the file content to the FileField
                    file_obj.file.save(filename, ContentFile(image_content), save=False)

                    # Ensure the file is accessible for hashing
                    file_obj.file.open()
                    file_obj.file.seek(0)

                    # Now save the File object - this will calculate the MD5 hash
                    file_obj.save()

                    # Close the file after saving
                    file_obj.file.close()

                    # Link the file to the person
                    person.photo = file_obj
                    person.save()

                    created += 1
                    processed += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Created photo for {display_name} (legacy_id={legacy_id})"
                        )
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error creating File object for {display_name} (legacy_id={legacy_id}): {e}"
                        )
                    )
                    errors += 1
                    continue

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Processed {processed} photos: {created} created, {skipped} skipped, {errors} errors"
            )
        )
