"""Tests for user_profile_pictures workbook recipe."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from wts_app.ingestion.copyright_metadata import resolve_file_metadata_ids
from wts_app.ingestion.orchestrator import commit_step, ensure_steps, save_draft
from wts_app.models import Person, Workbook, WorkbookFile, WorkbookStep
from wts_app.models.documents import CopyrightParty, File, Licence

User = get_user_model()


class CopyrightMetadataResolverTests(TestCase):
    def test_resolves_inline_licence_and_parties(self):
        licence = Licence.objects.create(name="Existing Licence")
        owner = CopyrightParty.objects.create(name="Existing Owner")

        resolved = resolve_file_metadata_ids(
            {
                "licence_create": {
                    "name": "CC BY 4.0",
                    "licence_url": "https://creativecommons.org/licenses/by/4.0/",
                },
                "copyright_owner_id": str(owner.id),
                "licence_grantor_create": {
                    "name": "New Grantor",
                    "website": "https://example.com/grantor",
                },
                "licence_id": str(licence.id),
            }
        )

        self.assertEqual(resolved["licence_id"], str(licence.id))
        self.assertEqual(resolved["copyright_owner_id"], str(owner.id))
        self.assertTrue(Licence.objects.filter(name="CC BY 4.0").exists())
        grantor = CopyrightParty.objects.get(name="New Grantor")
        self.assertEqual(grantor.website, "https://example.com/grantor")
        self.assertEqual(resolved["licence_grantor_id"], str(grantor.id))


class UserProfilePicturesRecipeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="test-pass",
            is_staff=True,
        )
        self.person = Person.objects.create(
            first_name="Jane",
            last_name="Doe",
            display_name="Jane Doe",
        )
        self.workbook = Workbook.objects.create(
            name="Profile photos",
            recipe_key="user_profile_pictures",
            user=self.user,
        )
        self.workbook_file = WorkbookFile.objects.create(
            workbook=self.workbook,
            file=SimpleUploadedFile(
                "jane.jpg",
                b"fake-image-bytes",
                content_type="image/jpeg",
            ),
        )
        ensure_steps(self.workbook, workbook_file=self.workbook_file)

    @patch("wts_app.ingestion.recipes.user_profile_pictures.promote_workbook_file")
    def test_publish_sets_person_photo(self, mock_promote):
        promoted = MagicMock(spec=File)
        promoted.id = "00000000-0000-0000-0000-000000000099"
        mock_promote.return_value = promoted

        link = WorkbookStep.objects.get(
            workbook=self.workbook,
            workbook_file=self.workbook_file,
            step_key="link_entities",
        )
        save_draft(
            link,
            {
                "workbook_file_id": str(self.workbook_file.id),
                "person_id": str(self.person.id),
                "original_url": "https://source.example/photo.jpg",
                "attribution_text": "Photo credit example",
                "file_metadata": {
                    "licence_create": {"name": "CC BY 4.0", "licence_url": "https://creativecommons.org/"},
                },
            },
        )
        commit_step(link, actor=self.user)

        publish = WorkbookStep.objects.get(
            workbook=self.workbook,
            workbook_file=self.workbook_file,
            step_key="publish_profile_picture",
        )
        commit_step(publish, actor=self.user)

        self.person.refresh_from_db()
        self.assertEqual(str(self.person.photo_id), str(promoted.id))
        mock_promote.assert_called_once()
        call_kwargs = mock_promote.call_args.kwargs
        self.assertEqual(
            call_kwargs["file_metadata"]["source_url"],
            "https://source.example/photo.jpg",
        )
        self.assertTrue(Licence.objects.filter(name="CC BY 4.0").exists())
