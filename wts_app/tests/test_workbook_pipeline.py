"""Tests for workbook ingestion pipeline."""

from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from wts_app.ingestion.orchestrator import commit_step, ensure_steps, save_draft
from wts_app.ingestion.recipes.credit_card import credit_card_statement_file_name
from wts_app.ingestion.recipes.ministerial_list import (
    MINISTERIAL_LIST_DOCUMENT_CATEGORY,
    ministerial_list_file_name,
    normalize_category,
    normalize_extracted_person_name,
    parse_position,
    suggest_person_id,
)
from wts_app.ingestion.promote import promote_workbook_file
from wts_app.models import (
    CreditCardExpense,
    CreditCardReconciliation,
    MinisterialAffiliation,
    MinisterialPortfolio,
    Person,
    Workbook,
    WorkbookFile,
    WorkbookStep,
)


class CreditCardStatementFileNameTests(TestCase):
    def test_single_month_period(self):
        name = credit_card_statement_file_name(
            person_display_name="Chris Penk",
            start_date="2025-07-01",
            end_date="2025-07-31",
        )
        self.assertEqual(
            name,
            "Ministerial credit card reconciliations and statements for Chris Penk for July 2025",
        )

    def test_multi_month_period(self):
        name = credit_card_statement_file_name(
            person_display_name="Chris Penk",
            start_date="2025-07-01",
            end_date="2025-09-30",
        )
        self.assertEqual(
            name,
            "Ministerial credit card reconciliations and statements for Chris Penk "
            "for July 2025 to September 2025",
        )


class MinisterialPersonNameNormalizationTests(TestCase):
    def test_strips_honorifics_and_postnominals(self):
        self.assertEqual(
            normalize_extracted_person_name("Rt Hon Christopher Luxon KC, MP"),
            "Christopher Luxon",
        )
        self.assertEqual(
            normalize_extracted_person_name("Hon Dr Ayesha Verrall MP"),
            "Ayesha Verrall",
        )
        self.assertEqual(
            normalize_extracted_person_name("Rt Hon Dr Winston Peters PC"),
            "Winston Peters",
        )

    def test_suggest_person_id_matches_display_name_after_normalization(self):
        person = Person.objects.create(
            first_name="Christopher",
            last_name="Luxon",
            display_name="Christopher Luxon",
        )
        self.assertEqual(
            suggest_person_id("Rt Hon Christopher Luxon KC, MP"),
            str(person.id),
        )


class MinisterialCategoryTests(TestCase):
    def test_normalize_category(self):
        self.assertEqual(normalize_category("p"), "p")
        self.assertEqual(normalize_category("r"), "r")
        self.assertEqual(normalize_category("portfolio"), "p")
        self.assertEqual(normalize_category("responsibility"), "r")
        self.assertEqual(normalize_category(None), "p")


class MinisterialPositionParsingTests(TestCase):
    def test_minister_of_portfolio(self):
        parsed = parse_position("Minister of Foreign Affairs")
        self.assertEqual(parsed["title"], "Minister")
        self.assertEqual(parsed["conjunction"], "of")
        self.assertEqual(parsed["portfolio_name"], "Foreign Affairs")

    def test_associate_minister_for_portfolio(self):
        parsed = parse_position("Associate Minister for Health")
        self.assertEqual(parsed["title"], "Associate Minister")
        self.assertEqual(parsed["conjunction"], "for")
        self.assertEqual(parsed["portfolio_name"], "Health")

    def test_prime_minister_is_portfolio_only(self):
        parsed = parse_position("Prime Minister")
        self.assertIsNone(parsed["title"])
        self.assertIsNone(parsed["conjunction"])
        self.assertEqual(parsed["portfolio_name"], "Prime Minister")

    def test_attorney_general_is_portfolio_only(self):
        parsed = parse_position("Attorney-General")
        self.assertIsNone(parsed["title"])
        self.assertIsNone(parsed["conjunction"])
        self.assertEqual(parsed["portfolio_name"], "Attorney-General")

    def test_minister_responsible_for_the(self):
        parsed = parse_position("Minister Responsible for the GCSB")
        self.assertEqual(parsed["title"], "Minister Responsible")
        self.assertEqual(parsed["conjunction"], "for the")
        self.assertEqual(parsed["portfolio_name"], "GCSB")


class MinisterialListPublishTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="ministerial-staff",
            email="ministerial@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.person = Person.objects.create(
            first_name="Chris",
            last_name="Luxon",
            display_name="Christopher Luxon",
        )
        self.other_person = Person.objects.create(
            first_name="Winston",
            last_name="Peters",
            display_name="Winston Peters",
        )
        self.portfolio = MinisterialPortfolio.objects.create(name="Foreign Affairs")
        self.workbook = Workbook.objects.create(
            name="Ministerial list",
            user=self.user,
            recipe_key="ministerial_list",
        )
        upload = SimpleUploadedFile(
            "list.pdf",
            b"%PDF-1.4 test",
            content_type="application/pdf",
        )
        self.workbook_file = WorkbookFile.objects.create(workbook=self.workbook)
        self.workbook_file.file.save("list.pdf", upload, save=True)
        ensure_steps(self.workbook, workbook_file=self.workbook_file)

    def _step(self, step_key: str) -> WorkbookStep:
        return WorkbookStep.objects.get(
            workbook=self.workbook,
            workbook_file=self.workbook_file,
            step_key=step_key,
        )

    @patch("wts_app.ingestion.recipes.ministerial_list.promote_workbook_file")
    def test_publish_ends_prior_incumbent_and_creates_affiliation(self, mock_promote):
        from wts_app.models import File

        mock_file = MagicMock(spec=File)
        mock_file.id = "00000000-0000-0000-0000-000000000099"
        mock_promote.return_value = mock_file

        existing = MinisterialAffiliation.objects.create(
            person=self.other_person,
            portfolio=self.portfolio,
            title="Minister",
            conjunction="of",
            type="p",
            start_date=date(2020, 1, 1),
        )

        gemini = self._step("gemini_extract")
        gemini.payload = {
            "proposal": {
                "people": [
                    {
                        "extracted_name": "Christopher Luxon",
                        "person_id": str(self.person.id),
                        "positions": [
                            {
                                "raw": "Minister of Foreign Affairs",
                                "title": "Minister",
                                "conjunction": "of",
                                "portfolio_name": "Foreign Affairs",
                                "portfolio_id": str(self.portfolio.id),
                                "category": "p",
                            }
                        ],
                    }
                ]
            }
        }
        gemini.status = WorkbookStep.Status.AWAITING_REVIEW
        gemini.save()
        commit_step(gemini, actor=self.user)

        link = self._step("link_entities")
        link.payload = {
            "workbook_file_id": str(self.workbook_file.id),
            "entries": [
                {
                    "extracted_name": "Christopher Luxon",
                    "person_id": str(self.person.id),
                    "positions": [
                        {
                            "raw": "Minister of Foreign Affairs",
                            "title": "Minister",
                            "conjunction": "of",
                            "portfolio_name": "Foreign Affairs",
                            "portfolio_id": str(self.portfolio.id),
                            "category": "p",
                        }
                    ],
                }
            ],
        }
        link.status = WorkbookStep.Status.AWAITING_REVIEW
        link.save()
        commit_step(link, actor=self.user)

        publish = self._step("publish_ministerial_list")
        publish.payload = {"effective_date": "2024-12-02"}
        commit_step(publish, actor=self.user)

        existing.refresh_from_db()
        self.assertEqual(existing.end_date, date(2024, 12, 1))

        new_aff = MinisterialAffiliation.objects.get(
            person=self.person,
            portfolio=self.portfolio,
            start_date=date(2024, 12, 2),
        )
        self.assertEqual(new_aff.title, "Minister")
        self.assertEqual(new_aff.conjunction, "of")

        file_metadata = mock_promote.call_args.kwargs["file_metadata"]
        self.assertEqual(
            file_metadata["file_name"],
            ministerial_list_file_name(effective_date="2024-12-02"),
        )

    @patch("wts_app.ingestion.recipes.ministerial_list.promote_workbook_file")
    def test_publish_applies_copyright_from_batch_defaults(self, mock_promote):
        from wts_app.models import File
        from wts_app.models.documents import CopyrightParty, Licence

        mock_file = MagicMock(spec=File)
        mock_file.id = "00000000-0000-0000-0000-000000000099"
        mock_promote.return_value = mock_file

        licence = Licence.objects.create(name="Crown Copyright")
        owner = CopyrightParty.objects.create(name="Department of Prime Minister")
        grantor = CopyrightParty.objects.create(name="Crown")

        self.workbook.batch_defaults = {
            "licence_id": str(licence.id),
            "copyright_owner_id": str(owner.id),
            "licence_grantor_id": str(grantor.id),
        }
        self.workbook.save(update_fields=["batch_defaults", "updated_at"])

        link = self._step("link_entities")
        link.payload = {
            "workbook_file_id": str(self.workbook_file.id),
            "entries": [
                {
                    "extracted_name": "Christopher Luxon",
                    "person_id": str(self.person.id),
                    "positions": [
                        {
                            "raw": "Minister of Foreign Affairs",
                            "title": "Minister",
                            "conjunction": "of",
                            "portfolio_name": "Foreign Affairs",
                            "portfolio_id": str(self.portfolio.id),
                            "category": "p",
                        }
                    ],
                }
            ],
        }
        link.status = WorkbookStep.Status.AWAITING_REVIEW
        link.save()
        commit_step(link, actor=self.user)

        gemini = self._step("gemini_extract")
        gemini.status = WorkbookStep.Status.COMMITTED
        gemini.save()

        publish = self._step("publish_ministerial_list")
        publish.payload = {"effective_date": "2024-12-02"}
        commit_step(publish, actor=self.user)

        file_metadata = mock_promote.call_args.kwargs["file_metadata"]
        self.assertEqual(file_metadata["licence_id"], str(licence.id))
        self.assertEqual(file_metadata["copyright_owner_id"], str(owner.id))
        self.assertEqual(file_metadata["licence_grantor_id"], str(grantor.id))
        self.assertEqual(file_metadata["published_date"], "2024-12-02")
        self.assertEqual(
            file_metadata["document_name"],
            ministerial_list_file_name(effective_date="2024-12-02"),
        )
        self.assertEqual(
            file_metadata["document_category_name"],
            MINISTERIAL_LIST_DOCUMENT_CATEGORY,
        )
        self.assertEqual(file_metadata["file_type"], "application/pdf")

    def test_promote_creates_document_and_sets_mime_type(self):
        from wts_app.models.documents import Document

        display_name = ministerial_list_file_name(effective_date="2024-12-02")
        file_obj = promote_workbook_file(
            self.workbook_file,
            file_metadata={
                "file_name": display_name,
                "file_description": "",
                "published_date": "2024-12-02",
                "document_name": display_name,
                "document_category_name": MINISTERIAL_LIST_DOCUMENT_CATEGORY,
                "file_type": "application/pdf",
            },
        )

        self.assertEqual(file_obj.published_date, date(2024, 12, 2))
        self.assertEqual(file_obj.file_type, "application/pdf")
        self.assertIsNotNone(file_obj.document_id)

        document = Document.objects.get(pk=file_obj.document_id)
        self.assertEqual(document.name, display_name)
        self.assertTrue(
            document.categories.filter(name=MINISTERIAL_LIST_DOCUMENT_CATEGORY).exists()
        )

    @patch("wts_app.ingestion.recipes.ministerial_list.promote_workbook_file")
    def test_publish_skips_when_active_affiliation_matches_exactly(self, mock_promote):
        from wts_app.models import File

        mock_file = MagicMock(spec=File)
        mock_file.id = "00000000-0000-0000-0000-000000000099"
        mock_promote.return_value = mock_file

        MinisterialAffiliation.objects.create(
            person=self.person,
            portfolio=self.portfolio,
            title="Minister",
            conjunction="of",
            type="p",
            start_date=date(2024, 12, 2),
        )

        link = self._step("link_entities")
        link.payload = {
            "workbook_file_id": str(self.workbook_file.id),
            "entries": [
                {
                    "extracted_name": "Christopher Luxon",
                    "person_id": str(self.person.id),
                    "positions": [
                        {
                            "raw": "Minister of Foreign Affairs",
                            "title": "Minister",
                            "conjunction": "of",
                            "portfolio_name": "Foreign Affairs",
                            "portfolio_id": str(self.portfolio.id),
                            "category": "p",
                        }
                    ],
                }
            ],
        }
        link.status = WorkbookStep.Status.AWAITING_REVIEW
        link.save()
        commit_step(link, actor=self.user)

        gemini = self._step("gemini_extract")
        gemini.status = WorkbookStep.Status.COMMITTED
        gemini.save()

        publish = self._step("publish_ministerial_list")
        publish.payload = {"effective_date": "2024-12-02"}
        commit_step(publish, actor=self.user)

        self.assertEqual(
            MinisterialAffiliation.objects.filter(
                person=self.person,
                portfolio=self.portfolio,
            ).count(),
            1,
        )

    @patch("wts_app.ingestion.recipes.ministerial_list.promote_workbook_file")
    def test_publish_ends_and_recreates_when_title_changes(self, mock_promote):
        from wts_app.models import File

        mock_file = MagicMock(spec=File)
        mock_file.id = "00000000-0000-0000-0000-000000000099"
        mock_promote.return_value = mock_file

        existing = MinisterialAffiliation.objects.create(
            person=self.person,
            portfolio=self.portfolio,
            title="Associate Minister",
            conjunction="of",
            type="p",
            start_date=date(2024, 6, 1),
        )

        link = self._step("link_entities")
        link.payload = {
            "workbook_file_id": str(self.workbook_file.id),
            "entries": [
                {
                    "extracted_name": "Christopher Luxon",
                    "person_id": str(self.person.id),
                    "positions": [
                        {
                            "raw": "Minister of Foreign Affairs",
                            "title": "Minister",
                            "conjunction": "of",
                            "portfolio_name": "Foreign Affairs",
                            "portfolio_id": str(self.portfolio.id),
                            "category": "p",
                        }
                    ],
                }
            ],
        }
        link.status = WorkbookStep.Status.AWAITING_REVIEW
        link.save()
        commit_step(link, actor=self.user)

        gemini = self._step("gemini_extract")
        gemini.status = WorkbookStep.Status.COMMITTED
        gemini.save()

        publish = self._step("publish_ministerial_list")
        publish.payload = {"effective_date": "2024-12-02"}
        commit_step(publish, actor=self.user)

        existing.refresh_from_db()
        self.assertEqual(existing.end_date, date(2024, 12, 1))
        self.assertTrue(
            MinisterialAffiliation.objects.filter(
                person=self.person,
                portfolio=self.portfolio,
                title="Minister",
                conjunction="of",
                start_date=date(2024, 12, 2),
            ).exists()
        )


class WorkbookPipelineTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.person = Person.objects.create(
            first_name="Test",
            last_name="Minister",
            display_name="Test Minister",
        )
        self.workbook = Workbook.objects.create(
            name="Batch test",
            user=self.user,
            recipe_key="credit_card_reconciliation",
        )
        upload = SimpleUploadedFile(
            "statement.pdf",
            b"%PDF-1.4 test",
            content_type="application/pdf",
        )
        self.workbook_file = WorkbookFile.objects.create(workbook=self.workbook)
        self.workbook_file.file.save("statement.pdf", upload, save=True)
        ensure_steps(self.workbook, workbook_file=self.workbook_file)

    def _step(self, step_key: str) -> WorkbookStep:
        return WorkbookStep.objects.get(
            workbook=self.workbook,
            workbook_file=self.workbook_file,
            step_key=step_key,
        )

    def test_link_entities_blocks_invalid_dates(self):
        step = self._step("link_entities")
        with self.assertRaises(Exception):
            save_draft(
                step,
                {
                    "person_id": str(self.person.id),
                    "start_date": "2025-02-01",
                    "end_date": "2025-01-01",
                    "workbook_file_id": str(self.workbook_file.id),
                },
            )

    @patch("wts_app.ingestion.recipes.credit_card.promote_workbook_file")
    def test_publish_promotes_from_gcs_and_creates_records(self, mock_promote):
        from wts_app.models import File

        mock_file = MagicMock(spec=File)
        mock_file.id = "00000000-0000-0000-0000-000000000099"
        mock_promote.return_value = mock_file

        link = self._step("link_entities")
        save_draft(
            link,
            {
                "person_id": str(self.person.id),
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "workbook_file_id": str(self.workbook_file.id),
            },
        )
        link.status = WorkbookStep.Status.AWAITING_REVIEW
        link.save()
        commit_step(link, actor=self.user)

        gemini = self._step("gemini_extract")
        gemini.payload = {
            "proposal": {
                "concerns": None,
                "expenses": [
                    {
                        "date": "2025-01-15",
                        "merchant_name": "Test Store",
                        "description": None,
                        "amount_nzd": 12.34,
                        "original_currency_code": "NZD",
                        "original_amount": 12.34,
                    }
                ],
            }
        }
        gemini.status = WorkbookStep.Status.AWAITING_REVIEW
        gemini.save()

        self.assertEqual(CreditCardExpense.objects.count(), 0)
        publish = self._step("publish_reconciliation")
        commit_step(publish, actor=self.user)
        file_metadata = mock_promote.call_args.kwargs["file_metadata"]
        mock_promote.assert_called_once_with(
            self.workbook_file,
            file_metadata=file_metadata,
        )
        self.assertEqual(
            file_metadata["file_name"],
            credit_card_statement_file_name(
                person_display_name=self.person.display_name,
                start_date="2025-01-01",
                end_date="2025-01-31",
            ),
        )
        self.assertEqual(file_metadata["file_description"], "")
        self.assertEqual(CreditCardReconciliation.objects.count(), 1)
        self.assertEqual(CreditCardExpense.objects.count(), 1)

    def test_per_file_isolation(self):
        upload2 = SimpleUploadedFile("b.pdf", b"%PDF-2", content_type="application/pdf")
        file2 = WorkbookFile.objects.create(workbook=self.workbook)
        file2.file.save("b.pdf", upload2, save=True)
        ensure_steps(self.workbook, workbook_file=file2)
        self.assertEqual(
            WorkbookStep.objects.filter(workbook=self.workbook).count(),
            8,
        )


class WorkbookLifecycleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="lifecycle-staff",
            email="lifecycle@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.workbook = Workbook.objects.create(
            name="Lifecycle test",
            user=self.user,
            recipe_key="credit_card_reconciliation",
        )
        upload = SimpleUploadedFile(
            "statement.pdf",
            b"%PDF-1.4 test",
            content_type="application/pdf",
        )
        self.workbook_file = WorkbookFile.objects.create(workbook=self.workbook)
        self.workbook_file.file.save("statement.pdf", upload, save=True)
        ensure_steps(self.workbook, workbook_file=self.workbook_file)

    def _step(self, step_key: str) -> WorkbookStep:
        return WorkbookStep.objects.get(
            workbook=self.workbook,
            workbook_file=self.workbook_file,
            step_key=step_key,
        )

    def test_close_task_marks_closed_and_deletes_staging_files(self):
        from wts_app.tasks.workbooks import close_completed_workbook

        for step in WorkbookStep.objects.filter(workbook=self.workbook):
            step.status = WorkbookStep.Status.COMMITTED
            step.save(update_fields=["status", "updated_at"])

        close_completed_workbook(str(self.workbook.id))

        self.workbook.refresh_from_db()
        self.assertEqual(self.workbook.status, Workbook.Status.CLOSED)
        self.assertEqual(self.workbook.files.count(), 0)

    @patch("wts_app.tasks.workbooks.close_completed_workbook.delay")
    @patch("wts_app.ingestion.recipes.credit_card.promote_workbook_file")
    def test_commit_last_step_schedules_close_task(self, mock_promote, mock_delay):
        from wts_app.models import File

        mock_file = MagicMock(spec=File)
        mock_file.id = "00000000-0000-0000-0000-000000000099"
        mock_promote.return_value = mock_file

        person = Person.objects.create(
            first_name="Test",
            last_name="Minister",
            display_name="Test Minister",
        )
        link = self._step("link_entities")
        link.payload = {
            "person_id": str(person.id),
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "workbook_file_id": str(self.workbook_file.id),
        }
        link.status = WorkbookStep.Status.AWAITING_REVIEW
        link.save()
        commit_step(link, actor=self.user)

        gemini = self._step("gemini_extract")
        gemini.payload = {
            "proposal": {
                "concerns": None,
                "expenses": [],
            }
        }
        gemini.status = WorkbookStep.Status.AWAITING_REVIEW
        gemini.save()
        commit_step(gemini, actor=self.user)

        publish = self._step("publish_reconciliation")
        commit_step(publish, actor=self.user)

        mock_delay.assert_called_once_with(str(self.workbook.id))
