"""
Client homepage view.

Provides recent bills, votes, and elections for the web client homepage.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import views
from rest_framework.response import Response

from ..models import Bill, Vote, Election
from .bills import BillSimpleSerializer
from .votes import VoteSimpleSerializer
from .elections import ElectionSimpleSerializer


class ClientHomepageView(views.APIView):
    """Return homepage data for the web client."""

    def get(self, request):
        bills = Bill.objects.order_by('-last_activity_date', '-updated_at')[:5]

        votes = Vote.objects.select_related('bill').order_by('-date')[:5]

        today = timezone.localdate()
        election_queryset = Election.objects.prefetch_related('electionresultversion_set')
        recent_elections = election_queryset.filter(
            polling_date__lte=today
        ).order_by('-polling_date')[:5]

        current_window_start = today - timedelta(days=5)
        current_window_end = today + timedelta(days=10)
        current_election = election_queryset.filter(
            polling_date__gte=current_window_start,
            polling_date__lte=current_window_end,
        ).order_by('-polling_date').first()

        return Response({
            'bills': BillSimpleSerializer(bills, many=True).data,
            'votes': VoteSimpleSerializer(votes, many=True).data,
            'election': ElectionSimpleSerializer(recent_elections, many=True).data,
            'current_election': (
                ElectionSimpleSerializer(current_election).data
                if current_election
                else None
            ),
        })
