"""
Election results views.

Views for election results data including persistent data, reference data, and elections.
"""

from rest_framework import generics, serializers, views
from rest_framework.response import Response
from ..models.elections import (
    Election,
    ElectionResultVersion,
    PersistentParty,
    PersistentCandidate,
    PersistentVotingPlace,
    ElectionElectorate,
    ElectionParty,
    ElectionCandidate,
    ElectionVotingPlace,
)
from .base import StandardResultsSetPagination


# Serializers - Only show IDs for foreign keys, not nested objects

class ElectionSerializer(serializers.ModelSerializer):
    """Serializer for Election with only IDs for foreign keys."""
    boundary_set = serializers.PrimaryKeyRelatedField(read_only=True)
    gazette_notices = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    
    class Meta:
        model = Election
        fields = '__all__'


class ElectionResultVersionSerializer(serializers.ModelSerializer):
    """Serializer for ElectionResultVersion with only IDs for foreign keys."""
    election = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = ElectionResultVersion
        fields = '__all__'


class PersistentPartySerializer(serializers.ModelSerializer):
    """Serializer for PersistentParty with only IDs for foreign keys."""
    party = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = PersistentParty
        fields = '__all__'


class PersistentCandidateSerializer(serializers.ModelSerializer):
    """Serializer for PersistentCandidate with only IDs for foreign keys."""
    person = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = PersistentCandidate
        fields = '__all__'


class PersistentVotingPlaceSerializer(serializers.ModelSerializer):
    """Serializer for PersistentVotingPlace with only IDs for foreign keys."""
    
    class Meta:
        model = PersistentVotingPlace
        fields = '__all__'


class ElectionElectorateSerializer(serializers.ModelSerializer):
    """Serializer for ElectionElectorate with only IDs for foreign keys."""
    results_version = serializers.PrimaryKeyRelatedField(read_only=True)
    electorate = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = ElectionElectorate
        fields = '__all__'


class ElectionPartySerializer(serializers.ModelSerializer):
    """Serializer for ElectionParty with only IDs for foreign keys."""
    results_version = serializers.PrimaryKeyRelatedField(read_only=True)
    party = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = ElectionParty
        fields = '__all__'


class ElectionCandidateSerializer(serializers.ModelSerializer):
    """Serializer for ElectionCandidate with only IDs for foreign keys."""
    results_version = serializers.PrimaryKeyRelatedField(read_only=True)
    electorate = serializers.PrimaryKeyRelatedField(read_only=True)
    party = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = ElectionCandidate
        fields = '__all__'


class ElectionVotingPlaceSerializer(serializers.ModelSerializer):
    """Serializer for ElectionVotingPlace with only IDs for foreign keys."""
    results_version = serializers.PrimaryKeyRelatedField(read_only=True)
    physical_electorate = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = ElectionVotingPlace
        fields = '__all__'


# Views

class PersistentDataDownloadView(views.APIView):
    """Download all persistent data (PersistentParty, PersistentCandidate, PersistentVotingPlace)."""
    
    def get(self, request):
        persistent_parties = PersistentParty.objects.all()
        persistent_candidates = PersistentCandidate.objects.all()
        persistent_voting_places = PersistentVotingPlace.objects.all()
        
        return Response({
            'persistent_parties': PersistentPartySerializer(persistent_parties, many=True).data,
            'persistent_candidates': PersistentCandidateSerializer(persistent_candidates, many=True).data,
            'persistent_voting_places': PersistentVotingPlaceSerializer(persistent_voting_places, many=True).data,
        })


class ElectionListCreateView(generics.ListCreateAPIView):
    """List all elections or create a new election."""
    queryset = Election.objects.all()
    serializer_class = ElectionSerializer
    pagination_class = StandardResultsSetPagination


class ElectionRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete an election."""
    queryset = Election.objects.all()
    serializer_class = ElectionSerializer
    lookup_field = 'slug'


class ElectionVersionListCreateView(generics.ListCreateAPIView):
    """List all versions for an election or create a new version."""
    
    def get_queryset(self):
        election_slug = self.kwargs['slug']
        return ElectionResultVersion.objects.filter(election__slug=election_slug)
    
    serializer_class = ElectionResultVersionSerializer
    pagination_class = StandardResultsSetPagination


class ResultsVersionReferenceDataView(views.APIView):
    """Get all reference data for a given results version (electorates, voting places, candidates, and parties)."""
    
    def get(self, request, slug, version_slug):
        try:
            results_version = ElectionResultVersion.objects.get(
                election__slug=slug,
                slug=version_slug
            )
        except ElectionResultVersion.DoesNotExist:
            return Response({'error': 'Results version not found'}, status=404)
        
        electorates = ElectionElectorate.objects.filter(results_version=results_version)
        voting_places = ElectionVotingPlace.objects.filter(results_version=results_version)
        candidates = ElectionCandidate.objects.filter(results_version=results_version)
        parties = ElectionParty.objects.filter(results_version=results_version)
        
        return Response({
            'results_version': ElectionResultVersionSerializer(results_version).data,
            'electorates': ElectionElectorateSerializer(electorates, many=True).data,
            'voting_places': ElectionVotingPlaceSerializer(voting_places, many=True).data,
            'candidates': ElectionCandidateSerializer(candidates, many=True).data,
            'parties': ElectionPartySerializer(parties, many=True).data,
        })

