from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from collections import defaultdict
from wts_app.models.documents import File


class Command(BaseCommand):
    help = "Identify File objects with the same MD5 hash (duplicates)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hash-field",
            type=str,
            choices=["stored_md5", "original_md5", "both"],
            default="stored_md5",
            help="Which MD5 hash field to check: 'stored_md5', 'original_md5', or 'both' (default: stored_md5)",
        )
        parser.add_argument(
            "--output-csv",
            type=str,
            help="Optional path to output CSV file with duplicate information",
        )
        parser.add_argument(
            "--min-count",
            type=int,
            default=2,
            help="Minimum number of files with same hash to report (default: 2)",
        )

    def handle(self, *args, **options):
        hash_field = options["hash_field"]
        output_csv = options.get("output_csv")
        min_count = options["min_count"]

        self.stdout.write("Finding duplicate files based on MD5 hash...")
        self.stdout.write(f"Using hash field: {hash_field}")
        self.stdout.write(f"Minimum count: {min_count}\n")

        # Get all files
        files = File.objects.all().select_related("document", "copyright_owner", "licence_grantor", "licence")
        
        # Group files by hash
        hash_groups = defaultdict(list)
        
        for file_obj in files:
            hashes_to_check = []
            
            if hash_field == "stored_md5" or hash_field == "both":
                if file_obj.stored_md5:
                    hashes_to_check.append(("stored_md5", file_obj.stored_md5))
            
            if hash_field == "original_md5" or hash_field == "both":
                if file_obj.original_md5:
                    hashes_to_check.append(("original_md5", file_obj.original_md5))
            
            for hash_type, hash_value in hashes_to_check:
                hash_groups[(hash_type, hash_value)].append(file_obj)
        
        # Filter to only groups with duplicates
        duplicate_groups = {
            (hash_type, hash_value): file_list
            for (hash_type, hash_value), file_list in hash_groups.items()
            if len(file_list) >= min_count
        }
        
        if not duplicate_groups:
            self.stdout.write(
                self.style.SUCCESS(
                    f"No duplicate files found (with minimum count of {min_count})"
                )
            )
            return
        
        # Report duplicates
        total_duplicates = 0
        total_files_in_duplicates = 0
        
        self.stdout.write(
            self.style.WARNING(
                f"\nFound {len(duplicate_groups)} hash(es) with duplicate files:\n"
            )
        )
        
        duplicate_data = []
        
        for (hash_type, hash_value), file_list in sorted(duplicate_groups.items()):
            count = len(file_list)
            total_files_in_duplicates += count
            # Number of duplicates = count - 1 (one is the original)
            duplicates = count - 1
            total_duplicates += duplicates
            
            self.stdout.write(
                self.style.WARNING(
                    f"\n{'='*80}\n"
                    f"Hash Type: {hash_type}\n"
                    f"MD5 Hash: {hash_value}\n"
                    f"Files with this hash: {count}\n"
                    f"{'='*80}"
                )
            )
            
            for idx, file_obj in enumerate(file_list, 1):
                file_info = {
                    "hash_type": hash_type,
                    "md5_hash": hash_value,
                    "file_id": str(file_obj.id),
                    "file_name": file_obj.file_name,
                    "file_type": file_obj.file_type,
                    "source_url": file_obj.source_url or "",
                    "document_id": str(file_obj.document.id) if file_obj.document else "",
                    "document_name": file_obj.document.name if file_obj.document else "",
                    "stored_md5": file_obj.stored_md5 or "",
                    "original_md5": file_obj.original_md5 or "",
                    "created_at": file_obj.created_at.isoformat() if file_obj.created_at else "",
                }
                duplicate_data.append(file_info)
                
                self.stdout.write(
                    f"\n  [{idx}/{count}] File ID: {file_obj.id}\n"
                    f"      Name: {file_obj.file_name}\n"
                    f"      Type: {file_obj.file_type}\n"
                    f"      Source URL: {file_obj.source_url or '(none)'}\n"
                    f"      Document: {file_obj.document.name if file_obj.document else '(none)'}\n"
                    f"      Stored MD5: {file_obj.stored_md5 or '(empty)'}\n"
                    f"      Original MD5: {file_obj.original_md5 or '(empty)'}\n"
                    f"      Created: {file_obj.created_at}\n"
                )
        
        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*80}\n"
                f"SUMMARY\n"
                f"{'='*80}\n"
                f"Total unique hashes with duplicates: {len(duplicate_groups)}\n"
                f"Total files in duplicate groups: {total_files_in_duplicates}\n"
                f"Total duplicate files: {total_duplicates}\n"
                f"Total unique files: {File.objects.count()}\n"
            )
        )
        
        # Output to CSV if requested
        if output_csv:
            import csv
            import os
            
            self.stdout.write(f"\nWriting duplicate information to CSV: {output_csv}")
            
            fieldnames = [
                "hash_type",
                "md5_hash",
                "file_id",
                "file_name",
                "file_type",
                "source_url",
                "document_id",
                "document_name",
                "stored_md5",
                "original_md5",
                "created_at",
            ]
            
            with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(duplicate_data)
            
            self.stdout.write(
                self.style.SUCCESS(f"CSV file written successfully: {output_csv}")
            )

