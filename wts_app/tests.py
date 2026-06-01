from django.test import TestCase, override_settings
from rest_framework.test import APIClient


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
