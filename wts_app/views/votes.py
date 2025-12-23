"""
Vote views.

Views for Vote and VoteRecord models.
"""

from rest_framework import generics, serializers
from ..models import Vote, VoteRecord
from .base import StandardResultsSetPagination
from .bills import BillSimpleSerializer
from .people import PersonSimpleSerializer


# Serializers
from ..models import Party

class PartySimpleSerializer(serializers.ModelSerializer):
    """Simple serializer for parties with minimal fields."""
    class Meta:
        model = Party
        fields = ['id', 'display_name', 'short_name', 'abbreviation']


class VoteRecordSerializer(serializers.ModelSerializer):
    """Serializer for vote records."""
    person = PersonSimpleSerializer(read_only=True)
    party = PartySimpleSerializer(read_only=True)
    
    class Meta:
        model = VoteRecord
        fields = '__all__'


class VoteSimpleSerializer(serializers.ModelSerializer):
    """Simple serializer for votes with minimal fields."""
    bill = BillSimpleSerializer(read_only=True)
    
    class Meta:
        model = Vote
        fields = ['id', 'bill', 'date', 'reading', 'ayes', 'noes', 'motion_agreed', 'vote_type']


class VoteSerializer(serializers.ModelSerializer):
    """Full serializer for votes with all fields and related objects."""
    bill = BillSimpleSerializer(read_only=True)
    vote_records = VoteRecordSerializer(many=True, read_only=True, source='voterecord_set')
    
    class Meta:
        model = Vote
        fields = '__all__'


# DRF Views
class VoteListCreateView(generics.ListCreateAPIView):
    """List all votes or create a new vote."""
    def get_queryset(self):
        queryset = Vote.objects.select_related('bill').prefetch_related('voterecord_set__person', 'voterecord_set__party').all()
        
        # Optional filtering
        bill_id = self.request.query_params.get('bill', None)
        if bill_id:
            queryset = queryset.filter(bill_id=bill_id)
        
        bill_legacy_id = self.request.query_params.get('bill_legacy_id', None)
        if bill_legacy_id:
            queryset = queryset.filter(bill__legacy_id=bill_legacy_id)
        
        reading = self.request.query_params.get('reading', None)
        if reading:
            try:
                reading_int = int(reading)
                queryset = queryset.filter(reading=reading_int)
            except (ValueError, TypeError):
                pass
        
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
        
        return queryset
    
    def get_serializer_class(self):
        if self.request and self.request.method == "GET":
            return VoteSerializer
        return VoteSerializer
    
    pagination_class = StandardResultsSetPagination


class VoteRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a vote."""
    def get_queryset(self):
        return Vote.objects.select_related('bill').prefetch_related('voterecord_set__person', 'voterecord_set__party').all()
    
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

