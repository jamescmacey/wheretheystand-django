"""
Election donation returns views.

Views for ElectionDonationReturn.
"""

from rest_framework import generics, serializers
from ..models.election_donation_returns import ElectionDonationReturn
from ..models.elections import PersistentCandidate, Election
from .base import StandardResultsSetPagination
from .documents import FileSerializer


# Serializers
class PersistentCandidateSimpleSerializer(serializers.ModelSerializer):
    """Simple persistent candidate serializer for nested representation."""
    class Meta:
        model = PersistentCandidate
        fields = ['id', 'display_name']

class ElectionSimpleSerializer(serializers.ModelSerializer):
    """Simple election serializer for nested representation."""
    class Meta:
        model = Election
        fields = ['id', 'name', 'polling_date', 'slug']

class ElectionDonationReturnSerializer(serializers.ModelSerializer):
    """Serializer for ElectionDonationReturn."""
    candidate = PersistentCandidateSimpleSerializer(read_only=True)
    election = ElectionSimpleSerializer(read_only=True)
    file = FileSerializer(read_only=True)
    
    class Meta:
        model = ElectionDonationReturn
        fields = '__all__'


# DRF Views
class ElectionDonationReturnListCreateView(generics.ListCreateAPIView):
    """List all election donation returns or create a new one."""
    
    def get_queryset(self):
        queryset = ElectionDonationReturn.objects.select_related(
            'candidate', 'election', 'file'
        ).all()
        
        # Filter by candidate (by ID)
        candidate_id = self.request.query_params.get('candidate', None)
        if candidate_id:
            queryset = queryset.filter(candidate_id=candidate_id)
        
        
        # Filter by election (by ID)
        election_id = self.request.query_params.get('election', None)
        if election_id:
            queryset = queryset.filter(election_id=election_id)

        # Filter by election (by slug)
        election_slug = self.request.query_params.get('election_slug', None)
        if election_slug:
            queryset = queryset.filter(election__slug=election_slug)
        
        return queryset
    
    serializer_class = ElectionDonationReturnSerializer
    pagination_class = StandardResultsSetPagination


class ElectionDonationReturnRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a election donation return."""
    queryset = ElectionDonationReturn.objects.select_related('candidate', 'election', 'file').all()
    serializer_class = ElectionDonationReturnSerializer
    lookup_field = 'pk'

