import csv
import os
import mimetypes
import urllib.request
import urllib.error
from django.core.management.base import BaseCommand, CommandError
from django.core.files.base import ContentFile
from django.utils import timezone
from django.conf import settings
from wts_app.models.documents import File, Licence, CopyrightParty


class Command(BaseCommand):
    help = "Create File objects from a CSV file, downloading files from URLs"

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to CSV file with columns: url, copyright_owner_name, licence_grantor_name, licence_name, file_name",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_file"]

        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        processed = 0
        created = 0
        skipped = 0
        errors = 0
        file_ids = []
        fieldnames = None

        # Read the CSV and process each row
        with open(csv_path, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            fieldnames = reader.fieldnames
            rows_data = []
            
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                url = row.get("url", "").strip()
                copyright_owner_name = row.get("copyright_owner_name", "").strip()
                licence_grantor_name = row.get("licence_grantor_name", "").strip()
                licence_name = row.get("licence_name", "").strip()
                file_name = row.get("file_name", "").strip()

                # Skip if URL or file_name is missing
                if not url or not file_name:
                    skipped += 1
                    file_ids.append("")
                    rows_data.append(row)
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping row {row_num}: missing url or file_name"
                        )
                    )
                    continue

                processed += 1

                try:
                    # Download the file
                    self.stdout.write(f"Downloading {url}...")
                    req = urllib.request.Request(url)
                    req.add_header("User-Agent", getattr(settings, "BOT_USER_AGENT", "Mozilla/5.0"))
                    
                    try:
                        with urllib.request.urlopen(req, timeout=30) as response:
                            file_content = response.read()
                            content_type = response.headers.get("Content-Type", "")
                    except (urllib.error.HTTPError, urllib.error.URLError) as e:
                        errors += 1
                        file_ids.append("")
                        rows_data.append(row)
                        self.stdout.write(
                            self.style.ERROR(
                                f"Error downloading {url}: {e}"
                            )
                        )
                        continue

                    # Determine file type
                    file_type, _ = mimetypes.guess_type(url)
                    if not file_type:
                        if content_type:
                            file_type = content_type.split(";")[0].strip()
                        else:
                            # Try to guess from file extension
                            ext = os.path.splitext(url)[1].lower()
                            if ext == ".pdf":
                                file_type = "application/pdf"
                            elif ext in [".jpg", ".jpeg"]:
                                file_type = "image/jpeg"
                            elif ext == ".png":
                                file_type = "image/png"
                            else:
                                file_type = "application/octet-stream"

                    # Get or create CopyrightParty for copyright_owner
                    copyright_owner = None
                    if copyright_owner_name:
                        copyright_owner, _ = CopyrightParty.objects.get_or_create(
                            name=copyright_owner_name
                        )

                    # Get or create CopyrightParty for licence_grantor
                    licence_grantor = None
                    if licence_grantor_name:
                        licence_grantor, _ = CopyrightParty.objects.get_or_create(
                            name=licence_grantor_name
                        )

                    # Get or create Licence
                    licence = None
                    if licence_name:
                        licence, _ = Licence.objects.get_or_create(
                            name=licence_name
                        )

                    # Extract filename from URL if needed for saving
                    filename_from_url = os.path.basename(url.split("?")[0])
                    if not filename_from_url or "." not in filename_from_url:
                        # Use file extension from content type if available
                        ext = mimetypes.guess_extension(file_type) or ""
                        filename_from_url = f"file{ext}"

                    # Create File object
                    file_obj = File(
                        file_name=file_name,
                        source_url=url,
                        file_type=file_type,
                        original_link_alive=True,
                        original_link_last_checked=timezone.now(),
                        copyright_owner=copyright_owner,
                        licence_grantor=licence_grantor,
                        licence=licence,
                    )

                    # Store the content temporarily so upload_to can access it for hashing
                    file_obj._file_content_for_hash = file_content

                    # Save the file content to the FileField
                    file_obj.file.save(filename_from_url, ContentFile(file_content), save=False)

                    # Now save the File object - this will calculate the MD5 hash
                    file_obj.save()

                    created += 1
                    file_ids.append(str(file_obj.id))
                    rows_data.append(row)
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Created File '{file_name}' with ID {file_obj.id}"
                        )
                    )

                except Exception as e:
                    errors += 1
                    file_ids.append("")
                    rows_data.append(row)
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error processing row {row_num}: {e}"
                        )
                    )

        # Write the output CSV with File IDs
        output_csv_path = csv_path.replace(".csv", "_with_ids.csv")
        self.stdout.write(f"\nWriting output CSV to {output_csv_path}...")
        
        # Write the output CSV with file_id column added
        output_fieldnames = list(fieldnames) + ["file_id"]
        with open(output_csv_path, mode="w", encoding="utf-8", newline="") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=output_fieldnames)
            writer.writeheader()
            
            for row_data, file_id in zip(rows_data, file_ids):
                row_data["file_id"] = file_id
                writer.writerow(row_data)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nFinished processing: {processed} processed, {created} created, "
                f"{skipped} skipped, {errors} errors"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(f"Output CSV saved to: {output_csv_path}")
        )

