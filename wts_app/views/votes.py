"""
Vote views.

Views for Vote and VoteRecord models.
"""

from django.db.models import Q
from rest_framework import generics, serializers
from ..models import Vote, VoteRecord
from .base import StandardResultsSetPagination
from .bills import BillSimpleSerializer, VALID_BILL_TYPES, _parse_bill_types
from .people import PersonSimpleSerializer


# Serializers
from ..models import Party

class PartySimpleSerializer(serializers.ModelSerializer):
    """Simple serializer for parties with minimal fields."""
    class Meta:
        model = Party
        fields = ['id', 'display_name', 'short_name', 'abbreviation', 'colour', 'slug']


class VoteRecordSerializer(serializers.ModelSerializer):
    """Serializer for vote records."""
    person = PersonSimpleSerializer(read_only=True)
    party = PartySimpleSerializer(read_only=True)
    
    class Meta:
        model = VoteRecord
        fields = '__all__'


VALID_VOTE_TYPE_CODES = {'voice', 'party', 'personal', 'split_party'}

VOTE_LIST_ORDERING = {
    '-date',
    'date',
    'bill__name',
    '-bill__name',
}


def _parse_csv_list(request, param):
    """Return a list from repeated or comma-separated query params."""
    raw = request.query_params.getlist(param)
    if raw:
        return [t.strip() for part in raw for t in part.split(',') if t.strip()]
    single = request.query_params.get(param)
    if single:
        return [t.strip() for t in single.split(',') if t.strip()]
    return []


def _apply_vote_type_filters(queryset, vote_types):
    """Filter by UI vote-type checkboxes (party vs split party are distinct)."""
    codes = [t for t in vote_types if t in VALID_VOTE_TYPE_CODES]
    if not codes:
        return queryset

    q = Q()
    if 'voice' in codes:
        q |= Q(vote_type='voice')
    if 'personal' in codes:
        q |= Q(vote_type='personal')
    if 'party' in codes:
        q |= Q(vote_type='party', contains_split_party_votes=False)
    if 'split_party' in codes:
        q |= Q(contains_split_party_votes=True)
    return queryset.filter(q)


class VoteSimpleSerializer(serializers.ModelSerializer):
    """Simple serializer for votes with minimal fields."""
    bill = BillSimpleSerializer(read_only=True)
    
    class Meta:
        model = Vote
        fields = [
            'id',
            'bill',
            'date',
            'reading',
            'ayes',
            'noes',
            'abstentions',
            'absentees',
            'motion_agreed',
            'vote_type',
            'contains_split_party_votes',
        ]

class VoteSimpleSerializerNoBill(serializers.ModelSerializer):
    """Simple serializer for votes with minimal fields."""
    class Meta:
        model = Vote
        fields = ['id', 'date', 'reading', 'ayes', 'noes', 'motion_agreed', 'vote_type']


class VoteSerializer(serializers.ModelSerializer):
    """Full serializer for votes with all fields and related objects."""
    bill = BillSimpleSerializer(read_only=True)
    vote_records = VoteRecordSerializer(many=True, read_only=True)
    
    class Meta:
        model = Vote
        fields = '__all__'


# DRF Views
class VoteListCreateView(generics.ListCreateAPIView):
    """List all votes or create a new vote."""
    def get_queryset(self):
        queryset = Vote.objects.select_related('bill').prefetch_related('vote_records__person', 'vote_records__party').all()
        
        # Optional filtering
        bill_id = self.request.query_params.get('bill', None)
        if bill_id:
            queryset = queryset.filter(bill_id=bill_id)
        
        bill_legacy_id = self.request.query_params.get('bill_legacy_id', None)
        if bill_legacy_id:
            queryset = queryset.filter(bill__legacy_id=bill_legacy_id)

        search = (self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(bill__name__icontains=search)

        bill_types = [t for t in _parse_bill_types(self.request) if t in VALID_BILL_TYPES]
        if bill_types:
            queryset = queryset.filter(bill__bill_type__in=bill_types)
        
        reading = self.request.query_params.get('reading', None)
        if reading:
            try:
                reading_int = int(reading)
                queryset = queryset.filter(reading=reading_int)
            except (ValueError, TypeError):
                pass

        vote_types = _parse_csv_list(self.request, 'vote_types')
        if vote_types:
            queryset = _apply_vote_type_filters(queryset, vote_types)
        else:
            vote_type = self.request.query_params.get('vote_type', None)
            if vote_type:
                queryset = queryset.filter(vote_type=vote_type)
        
        date_from = self.request.query_params.get('date_from', None)
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        
        date_to = self.request.query_params.get('date_to', None)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        
        motion_agreed = self.request.query_params.get('motion_agreed', None)
        if motion_agreed is not None:
            motion_agreed_bool = motion_agreed.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(motion_agreed=motion_agreed_bool)

        contains_split_party_votes = self.request.query_params.get('contains_split_party_votes', None)
        if contains_split_party_votes is not None:
            contains_split_party_votes_bool = contains_split_party_votes.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(contains_split_party_votes=contains_split_party_votes_bool)

        person_slug = self.request.query_params.get('person_slug', None)
        if person_slug:
            queryset = queryset.filter(vote_records__person__slug=person_slug).distinct()

        ordering = self.request.query_params.get('ordering', '-date')
        if ordering in VOTE_LIST_ORDERING:
            queryset = queryset.order_by(ordering)
        
        return queryset
    
    def get_serializer_class(self):
        if self.request and self.request.method == "GET":
            return VoteSimpleSerializer
        return VoteSerializer
    
    pagination_class = StandardResultsSetPagination


class VoteRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a vote."""
    def get_queryset(self):
        return Vote.objects.select_related('bill').prefetch_related('vote_records__person', 'vote_records__party').all()
    
    serializer_class = VoteSerializer
    lookup_field = 'pk'  # Using UUID primary key


class VoteRecordListCreateView(generics.ListCreateAPIView):
    """List all vote records or create a new vote record."""
    def get_queryset(self):
        queryset = VoteRecord.objects.select_related('vote', 'person', 'party').all()
        
        # Optional filtering
        vote_id = self.request.query_params.get('vote', None)
        if vote_id:
            queryset = queryset.filter(vote_id=vote_id)
        
        person_id = self.request.query_params.get('person', None)
        if person_id:
            queryset = queryset.filter(person_id=person_id)
        
        person_slug = self.request.query_params.get('person_slug', None)
        if person_slug:
            queryset = queryset.filter(person__slug=person_slug)
        
        party_id = self.request.query_params.get('party', None)
        if party_id:
            queryset = queryset.filter(party_id=party_id)
        
        position = self.request.query_params.get('position', None)
        if position:
            queryset = queryset.filter(position=position)
        
        is_proxy_vote = self.request.query_params.get('is_proxy_vote', None)
        if is_proxy_vote is not None:
            is_proxy_bool = is_proxy_vote.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(is_proxy_vote=is_proxy_bool)
        
        is_split_party_vote = self.request.query_params.get('is_split_party_vote', None)
        if is_split_party_vote is not None:
            is_split_bool = is_split_party_vote.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(is_split_party_vote=is_split_bool)
        
        return queryset
    
    serializer_class = VoteRecordSerializer
    pagination_class = StandardResultsSetPagination


class VoteRecordRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a vote record."""
    def get_queryset(self):
        return VoteRecord.objects.select_related('vote', 'person', 'party').all()
    
    serializer_class = VoteRecordSerializer
    lookup_field = 'pk'  # Using UUID primary key

