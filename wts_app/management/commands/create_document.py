import mimetypes
import os
from datetime import datetime
from typing import Optional

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from wts_app.models.documents import (
    Category,
    CopyrightParty,
    Document,
    File,
    Licence,
)


class Command(BaseCommand):
    help = "Interactive wizard to create a document and attach files."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Document creation wizard"))
        document = self._get_or_create_document()
        self._maybe_add_files(document)
        self.stdout.write(self.style.SUCCESS(f"Finished. Document id: {document.id}"))

    def _get_or_create_document(self) -> Document:
        while True:
            existing_id = input("Enter existing document ID to attach files (blank to create new): ").strip()
            if existing_id:
                try:
                    document = Document.objects.get(id=existing_id)
                    self.stdout.write(self.style.SUCCESS(f"Found document '{document.name}'"))
                    return document
                except Document.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f"No document found with id {existing_id}."))
                    continue
            return self._create_document()

    def _create_document(self) -> Document:
        name = self._prompt_required("Document name")
        description = self._prompt_optional("Description")

        categories = self._prompt_categories()

        document = Document.objects.create(
            name=name,
            description=description or None,
        )
        if categories:
            document.categories.set(categories)

        self.stdout.write(self.style.SUCCESS(f"Created document '{document.name}'"))
        return document

    def _maybe_add_files(self, document: Document) -> None:
        while self._confirm("Add a file to this document?"):
            file_info = self._prompt_file_info()
            if not file_info:
                self.stdout.write(self.style.WARNING("File skipped."))
                continue
            self._create_file(document, **file_info)

    def _prompt_file_info(self):
        file_path = self._prompt_required("Path to file (local filesystem)")
        if not os.path.isfile(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return None

        default_type, _ = mimetypes.guess_type(file_path)
        default_type = default_type or (os.path.splitext(file_path)[1].lstrip(".") or "unknown")

        file_name = self._prompt_with_default("File name", os.path.basename(file_path))
        file_description = self._prompt_optional("File description")
        file_type = self._prompt_with_default("File type", default_type)
        source_url = self._prompt_optional("Source URL")
        published_date = self._prompt_date("Published date (YYYY-MM-DD, blank to skip)")

        copyright_owner = self._prompt_copyright_party("Copyright owner (blank to skip)")
        licence = self._prompt_licence("Licence (blank to skip)")
        licence_grantor = self._prompt_copyright_party("Licence grantor (blank to skip)")

        return {
            "file_path": file_path,
            "file_name": file_name,
            "file_description": file_description,
            "file_type": file_type,
            "source_url": source_url,
            "published_date": published_date,
            "copyright_owner": copyright_owner,
            "licence": licence,
            "licence_grantor": licence_grantor,
        }

    def _create_file(
        self,
        document: Document,
        file_path: str,
        file_name: str,
        file_description: Optional[str],
        file_type: str,
        source_url: Optional[str],
        published_date,
        copyright_owner,
        licence,
        licence_grantor,
    ) -> File:
        with open(file_path, "rb") as fh:
            content = fh.read()

        file_obj = File(
            document=document,
            file_name=file_name,
            file_description=file_description or None,
            source_url=source_url or None,
            file_type=file_type,
            published_date=published_date,
            copyright_owner=copyright_owner,
            licence=licence,
            licence_grantor=licence_grantor,
        )

        # upload_to uses this attribute to hash the content without re-reading from storage
        file_obj._file_content_for_hash = content
        file_obj.file.save(os.path.basename(file_path), ContentFile(content), save=False)
        file_obj.save()

        self.stdout.write(self.style.SUCCESS(f"Attached file '{file_name}'"))
        return file_obj

    def _prompt_categories(self):
        categories = []
        existing = Category.objects.all().order_by("name")
        if existing.exists():
            self.stdout.write("Existing categories:")
            for category in existing:
                self.stdout.write(f" - {category.slug or slugify(category.name)} :: {category.name}")
        raw = input("Enter comma-separated category slugs to attach (blank to skip): ").strip()
        if not raw:
            return categories

        for slug in [part.strip() for part in raw.split(",") if part.strip()]:
            try:
                category = Category.objects.get(slug=slug)
            except Category.DoesNotExist:
                if not self._confirm(f"Category '{slug}' not found. Create it?"):
                    self.stdout.write(self.style.WARNING(f"Skipping category '{slug}'."))
                    continue
                name = self._prompt_with_default("Category name", slug.replace("-", " ").title())
                description = self._prompt_required("Category description")
                category = Category.objects.create(name=name, description=description, slug=slugify(slug))
            categories.append(category)

        return categories

    def _prompt_required(self, prompt: str) -> str:
        while True:
            value = input(f"{prompt}: ").strip()
            if value:
                return value
            self.stdout.write(self.style.ERROR("This field is required."))

    def _prompt_optional(self, prompt: str):
        value = input(f"{prompt}: ").strip()
        return value or None

    def _prompt_with_default(self, prompt: str, default: str) -> str:
        value = input(f"{prompt} [{default}]: ").strip()
        return value or default

    def _prompt_date(self, prompt: str):
        while True:
            raw = input(f"{prompt}: ").strip()
            if not raw:
                return None
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                self.stdout.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD or leave blank."))

    def _confirm(self, prompt: str, default: bool = True) -> bool:
        suffix = "Y/n" if default else "y/N"
        response = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not response:
            return default
        return response in {"y", "yes"}

    def _prompt_copyright_party(self, prompt: str):
        name = self._prompt_optional(prompt)
        if not name:
            return None
        description = self._prompt_optional("Description for this party (blank to skip)")
        website = self._prompt_optional("Website (blank to skip)")
        party, _ = CopyrightParty.objects.get_or_create(
            name=name,
            defaults={"description": description, "website": website},
        )
        return party

    def _prompt_licence(self, prompt: str):
        name = self._prompt_optional(prompt)
        if not name:
            return None
        description = self._prompt_optional("Licence description (blank to skip)")
        licence_url = self._prompt_optional("Licence URL (blank to skip)")
        licence, _ = Licence.objects.get_or_create(
            name=name,
            defaults={"description": description, "licence_url": licence_url},
        )
        return licence

