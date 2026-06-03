from datetime import date

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Bill, Vote


@override_settings(TURNSTILE_BYPASS_CODE="test-bypass-token")
class FeedbackCreateViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_feedback_with_turnstile_bypass(self):
        response = self.client.post(
            "/v2/feedback/",
            {
                "category": "feedback",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "message": "Hello from tests.",
                "turnstile": "test-bypass-token",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["category"], "feedback")
        self.assertEqual(response.data["name"], "Jane Doe")

    def test_rejects_invalid_turnstile(self):
        response = self.client.post(
            "/v2/feedback/",
            {
                "category": "general",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "message": "Hello.",
                "turnstile": "not-valid",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("turnstile", response.data)


class LegacyMigrationViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.bill = Bill.objects.create(name="Test Bill", legacy_id=1001)
        self.vote = Vote.objects.create(
            bill=self.bill,
            legacy_id=2002,
            date=date(2024, 1, 15),
            reading=1,
            ayes=60,
            noes=59,
            abstentions=0,
            absentees=1,
        )

    def test_bill_legacy_migration_returns_uuid(self):
        response = self.client.get("/v2/migration/bills/1001/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.bill.id))

    def test_bill_legacy_migration_not_found(self):
        response = self.client.get("/v2/migration/bills/9999/")
        self.assertEqual(response.status_code, 404)

    def test_vote_legacy_migration_returns_uuid(self):
        response = self.client.get("/v2/migration/votes/2002/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.vote.id))

    def test_vote_legacy_migration_not_found(self):
        response = self.client.get("/v2/migration/votes/9999/")
        self.assertEqual(response.status_code, 404)
