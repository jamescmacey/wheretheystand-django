"""
Timeline views.

Views for person timeline.
"""

from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from ..models import (
    Person, Bill, Vote, VoteRecord, CreditCardReconciliation,
    ParliamentaryAffiliation, PartyAffiliation
)
from ..models.documents import File
from ..models.parliaments import Parliament
from ..models.electorates import Electorate
from ..models.parties import Party


# Timeline-specific serializers (minimal fields only)
class TimelineBillSerializer(serializers.ModelSerializer):
    """Minimal serializer for bills in timeline."""
    class Meta:
        model = Bill
        fields = ['id', 'name', 'ref', 'bill_type', 'status', 'introduction_date']


class TimelineBillSimpleSerializer(serializers.ModelSerializer):
    """Minimal serializer for bill reference in vote timeline."""
    class Meta:
        model = Bill
        fields = ['id', 'name', 'ref']


class TimelineVoteSerializer(serializers.ModelSerializer):
    """Minimal serializer for votes in timeline."""
    bill = TimelineBillSimpleSerializer(read_only=True)
    position = serializers.SerializerMethodField()
    
    class Meta:
        model = Vote
        fields = ['id', 'bill', 'date', 'reading', 'motion_agreed', 'vote_type', 'position']
    
    def get_position(self, obj):
        """Get the person's voting position from the vote record."""
        # Use prefetched vote records if available (more efficient)
        if hasattr(obj, 'person_vote_records') and obj.person_vote_records:
            return obj.person_vote_records[0].position
        # Fallback to querying if prefetch wasn't used
        person = self.context.get('person')
        if person:
            try:
                vote_record = obj.vote_records.get(person=person)
                return vote_record.position
            except VoteRecord.DoesNotExist:
                return None
        return None


class TimelineFileSerializer(serializers.ModelSerializer):
    """Minimal serializer for files in timeline."""
    class Meta:
        model = File
        fields = ['id', 'file']


class TimelineCreditCardReconciliationSerializer(serializers.ModelSerializer):
    """Minimal serializer for credit card reconciliations in timeline."""
    file = TimelineFileSerializer(read_only=True)
    
    class Meta:
        model = CreditCardReconciliation
        fields = ['id', 'start_date', 'end_date', 'file']


class TimelineParliamentSerializer(serializers.ModelSerializer):
    """Minimal serializer for parliament in timeline."""
    class Meta:
        model = Parliament
        fields = ['id', 'number', 'start_date', 'end_date']


class TimelineElectorateSerializer(serializers.ModelSerializer):
    """Minimal serializer for electorate in timeline."""
    class Meta:
        model = Electorate
        fields = ['id', 'name', 'slug']


class TimelineParliamentaryAffiliationSerializer(serializers.ModelSerializer):
    """Minimal serializer for parliamentary affiliations in timeline."""
    parliament = TimelineParliamentSerializer(read_only=True)
    electorate = TimelineElectorateSerializer(read_only=True)
    
    class Meta:
        model = ParliamentaryAffiliation
        fields = ['id', 'parliament', 'electorate', 'elected_date', 'sworn_date', 'end_date', 'start_reason', 'end_reason']


class TimelinePartySerializer(serializers.ModelSerializer):
    """Minimal serializer for party in timeline."""
    class Meta:
        model = Party
        fields = ['id', 'display_name', 'short_name', 'abbreviation']


class TimelinePartyAffiliationSerializer(serializers.ModelSerializer):
    """Minimal serializer for party affiliations in timeline."""
    party = TimelinePartySerializer(read_only=True)
    
    class Meta:
        model = PartyAffiliation
        fields = ['id', 'party', 'start_date', 'end_date']


class PersonTimelineView(generics.RetrieveAPIView):
    """
    Get timeline of recent events for a person.
    
    Returns the n (default 10) most recent events from:
    - Bills (by introduction_date)
    - Votes (by vote date)
    - Credit card reconciliations (by created_at)
    - Parliamentary affiliations (by start date and end date)
    - Party affiliations (by start date and end date)
    """
    
    def get(self, request, slug):
        # Get person
        try:
            person = Person.objects.get(slug=slug)
        except Person.DoesNotExist:
            raise NotFound("Person not found")
        
        # Get limit from query params (default 10)
        try:
            limit = max(1, int(request.query_params.get('limit', 15)))
        except (ValueError, TypeError):
            limit = 15
        
        try:
            per_category_limit = max(1, int(request.query_params.get('per_category_limit', 15)))
        except (ValueError, TypeError):
            per_category_limit = 15

        # Ensure that limit and per_category_limit are no more than 30
        limit = min(limit, 30)
        per_category_limit = min(per_category_limit, 30)
        
        timeline_events = []
        
        # 1. Bills for the person (by introduction_date)
        bills = Bill.objects.filter(
            people_responsible=person,
            introduction_date__isnull=False
        ).order_by('-introduction_date')[:per_category_limit]
        
        for bill in bills:
            timeline_events.append({
                'type': 'bill_introduction',
                'date': bill.introduction_date.isoformat() if bill.introduction_date else None,
                'item': TimelineBillSerializer(bill, context={'request': request}).data
            })
        
        # 2. Votes for the person (by vote date)
        from django.db.models import Prefetch
        votes = Vote.objects.filter(
            vote_records__person=person
        ).select_related('bill').prefetch_related(
            Prefetch('vote_records', queryset=VoteRecord.objects.filter(person=person), to_attr='person_vote_records')
        ).distinct().order_by('-date')[:per_category_limit]
        
        for vote in votes:
            timeline_events.append({
                'type': 'vote',
                'date': vote.date.isoformat() if vote.date else None,
                'item': TimelineVoteSerializer(vote, context={'request': request, 'person': person}).data
            })
        
        # 3. Credit card reconciliations (by created_at)
        reconciliations = CreditCardReconciliation.objects.filter(
            person=person,
            hidden_from_timeline=False
        ).select_related('person', 'file').order_by('-created_at')[:per_category_limit]
        
        for reconciliation in reconciliations:
            timeline_events.append({
                'type': 'ministerial_credit_card_reconciliation',
                'date': reconciliation.created_at.isoformat() if reconciliation.created_at else None,
                'item': TimelineCreditCardReconciliationSerializer(reconciliation, context={'request': request}).data
            })
        
        # 4. Parliamentary affiliations - start dates
        # Use sworn_date if available, otherwise elected_date
        parliamentary_starts = ParliamentaryAffiliation.objects.filter(
            person=person
        ).select_related('parliament', 'electorate', 'election', 'gazette_notice_election', 'gazette_notice_vacation').order_by('-sworn_date', '-elected_date')[:per_category_limit]
        
        for affiliation in parliamentary_starts:
            # Use sworn_date if available, otherwise elected_date
            start_date = affiliation.sworn_date or affiliation.elected_date
            if start_date:
                timeline_events.append({
                    'type': 'parliamentary_affiliation_start',
                    'date': start_date.isoformat(),
                    'item': TimelineParliamentaryAffiliationSerializer(affiliation, context={'request': request}).data
                })
        
        # 5. Parliamentary affiliations - end dates
        parliamentary_ends = ParliamentaryAffiliation.objects.filter(
            person=person,
            end_date__isnull=False
        ).select_related('parliament', 'electorate', 'election', 'gazette_notice_election', 'gazette_notice_vacation').order_by('-end_date')[:per_category_limit]
        
        for affiliation in parliamentary_ends:
            timeline_events.append({
                'type': 'parliamentary_affiliation_end',
                'date': affiliation.end_date.isoformat(),
                'item': TimelineParliamentaryAffiliationSerializer(affiliation, context={'request': request}).data
            })
        
        # 6. Party affiliations - start dates
        party_starts = PartyAffiliation.objects.filter(
            person=person
        ).select_related('party').order_by('-start_date')[:per_category_limit]
        
        for affiliation in party_starts:
            timeline_events.append({
                'type': 'party_affiliation_start',
                'date': affiliation.start_date.isoformat(),
                'item': TimelinePartyAffiliationSerializer(affiliation, context={'request': request}).data
            })
        
        # 7. Party affiliations - end dates
        party_ends = PartyAffiliation.objects.filter(
            person=person,
            end_date__isnull=False
        ).select_related('party').order_by('-end_date')[:per_category_limit]
        
        for affiliation in party_ends:
            timeline_events.append({
                'type': 'party_affiliation_end',
                'date': affiliation.end_date.isoformat(),
                'item': TimelinePartyAffiliationSerializer(affiliation, context={'request': request}).data
            })
        
        # Sort all events by date (most recent first), filtering out events without dates
        timeline_events = [event for event in timeline_events if event['date'] is not None]
        timeline_events.sort(key=lambda x: x['date'], reverse=True)
        
        # Return the n most recent events
        timeline_events = timeline_events[:limit]
        
        return Response({
            'timeline': timeline_events
        })

