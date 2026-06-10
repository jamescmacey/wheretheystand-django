"""Tests for workbook Gemini submission failure handling."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from wts_app.gemini.processors import WorkbookStepGeminiProcessor
from wts_app.gemini.utils import fail_stale_unsubmitted_batch_job
from wts_app.ingestion.gemini import submit_gemini_for_step
from wts_app.ingestion.orchestrator import commit_step, ensure_steps
from wts_app.models import (
    GeminiBatchItem,
    GeminiBatchJob,
    Person,
    Workbook,
    WorkbookFile,
    WorkbookStep,
)


@override_settings(GEMINI_MODEL="gemini-2.5-flash")
class SubmitGeminiForStepFailureTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="gemini-staff",
            email="gemini@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.person = Person.objects.create(
            first_name="Test",
            last_name="Minister",
            display_name="Test Minister",
        )
        self.workbook = Workbook.objects.create(
            name="Gemini failure test",
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

        link = self._step("link_entities")
        link.payload = {
            "person_id": str(self.person.id),
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "workbook_file_id": str(self.workbook_file.id),
        }
        link.status = WorkbookStep.Status.AWAITING_REVIEW
        link.save()
        commit_step(link, actor=self.user)

        self.gemini_step = self._step("gemini_extract")
        self.gemini_step.status = WorkbookStep.Status.DRAFT
        self.gemini_step.save(update_fields=["status", "updated_at"])

    def _step(self, step_key: str) -> WorkbookStep:
        return WorkbookStep.objects.get(
            workbook=self.workbook,
            workbook_file=self.workbook_file,
            step_key=step_key,
        )

    @patch("wts_app.ingestion.gemini.GeminiClient")
    def test_build_request_failure_marks_records_failed_and_allows_retry(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_processor = MagicMock()
        mock_processor.name = "workbook_step_gemini"
        mock_processor.build_request.side_effect = ValueError("schema validation failed")

        with patch(
            "wts_app.ingestion.gemini.get_processor",
            return_value=mock_processor,
        ):
            with self.assertRaises(ValueError):
                submit_gemini_for_step(self.gemini_step)

        self.gemini_step.refresh_from_db()
        self.assertEqual(self.gemini_step.status, WorkbookStep.Status.DRAFT)
        self.assertIn("schema validation failed", self.gemini_step.error_message)

        job = GeminiBatchJob.objects.get()
        self.assertEqual(job.status, GeminiBatchJob.Status.FAILED)
        self.assertIsNone(job.batch_name)

        item = GeminiBatchItem.objects.get()
        self.assertEqual(item.status, GeminiBatchItem.Status.FAILED)

        processor = WorkbookStepGeminiProcessor(client=mock_client)
        retryable = processor.get_queryset()
        self.assertIn(self.gemini_step, retryable)

    @patch("wts_app.ingestion.gemini.GeminiClient")
    def test_orphan_pending_item_does_not_block_retry(self, mock_client_cls):
        job = GeminiBatchJob.objects.create(
            processor="workbook_step_gemini",
            requested_model="gemini-2.5-flash",
            status=GeminiBatchJob.Status.PENDING,
        )
        GeminiBatchItem.objects.create(
            job=job,
            content_object=self.gemini_step,
            status=GeminiBatchItem.Status.PENDING,
        )

        processor = WorkbookStepGeminiProcessor(client=mock_client_cls.return_value)
        retryable = processor.get_queryset()
        self.assertIn(self.gemini_step, retryable)


class FailStaleUnsubmittedBatchJobTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="orphan-staff",
            email="orphan@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.workbook = Workbook.objects.create(
            name="Orphan job test",
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
        self.gemini_step = WorkbookStep.objects.get(
            workbook=self.workbook,
            workbook_file=self.workbook_file,
            step_key="gemini_extract",
        )
        self.gemini_step.status = WorkbookStep.Status.RUNNING
        self.gemini_step.save(update_fields=["status", "updated_at"])

    def test_stale_orphan_job_is_failed_and_step_released(self):
        job = GeminiBatchJob.objects.create(
            processor="workbook_step_gemini",
            requested_model="gemini-2.5-flash",
            status=GeminiBatchJob.Status.PENDING,
        )
        GeminiBatchJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - timedelta(minutes=5),
        )
        job.refresh_from_db()
        item = GeminiBatchItem.objects.create(
            job=job,
            content_object=self.gemini_step,
            status=GeminiBatchItem.Status.PENDING,
        )

        self.assertTrue(fail_stale_unsubmitted_batch_job(job))

        job.refresh_from_db()
        item.refresh_from_db()
        self.gemini_step.refresh_from_db()
        self.assertEqual(job.status, GeminiBatchJob.Status.FAILED)
        self.assertEqual(item.status, GeminiBatchItem.Status.FAILED)
        self.assertEqual(self.gemini_step.status, WorkbookStep.Status.DRAFT)

    def test_recent_orphan_job_is_left_alone(self):
        job = GeminiBatchJob.objects.create(
            processor="workbook_step_gemini",
            requested_model="gemini-2.5-flash",
            status=GeminiBatchJob.Status.PENDING,
        )
        GeminiBatchItem.objects.create(
            job=job,
            content_object=self.gemini_step,
            status=GeminiBatchItem.Status.PENDING,
        )

        self.assertFalse(fail_stale_unsubmitted_batch_job(job))
        job.refresh_from_db()
        self.assertEqual(job.status, GeminiBatchJob.Status.PENDING)
