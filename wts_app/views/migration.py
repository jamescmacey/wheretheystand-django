"""
Legacy v1 ID → v2 UUID lookups for bills and votes.
"""

from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models import Bill, Vote


class BillLegacyMigrationView(views.APIView):
    """Resolve a v1 bill legacy_id to the current bill UUID."""

    permission_classes = [AllowAny]

    def get(self, request, legacy_id: int):
        try:
            bill = Bill.objects.only("id").get(legacy_id=legacy_id)
        except Bill.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"id": str(bill.id)})


class VoteLegacyMigrationView(views.APIView):
    """Resolve a v1 vote legacy_id to the current vote UUID."""

    permission_classes = [AllowAny]

    def get(self, request, legacy_id: int):
        try:
            vote = Vote.objects.only("id").get(legacy_id=legacy_id)
        except Vote.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"id": str(vote.id)})
