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
    ResultsSet,
    Result,
)
from ..models.electorates import Electorate
from ..models.people import Person
from .electorates import ElectorateSerializer, ElectorateBoundarySetSerializer
from .elections import ElectionSerializer, ElectionResultVersionSerializer
from .gazette import GazetteNoticeSerializer
from .base import StandardResultsSetPagination
# Import these here to avoid circular imports - will be used in full serializers
from .people import PersonSimpleSerializer
from .members_of_parliament import PartySerializer


# Serializers - Only show IDs for foreign keys, not nested objects

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


class ResultSerializer(serializers.ModelSerializer):
    """Serializer for Result with only IDs for foreign keys."""
    candidate = serializers.PrimaryKeyRelatedField(read_only=True)
    party = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = Result
        fields = ['candidate', 'party', 'count', 'per_cent', 'list_seats', 'electorate_seats', 'total_seats']


class ResultsSetSerializer(serializers.ModelSerializer):
    """Serializer for ResultsSet with only IDs for foreign keys and nested results."""
    results_version = serializers.PrimaryKeyRelatedField(read_only=True)
    electorate = serializers.PrimaryKeyRelatedField(read_only=True)
    voting_place = serializers.PrimaryKeyRelatedField(read_only=True)
    results = ResultSerializer(many=True, read_only=True, source='result_set')
    
    class Meta:
        model = ResultsSet
        fields = '__all__'


# Full nested serializers for person results view
class ElectionSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Election
        fields = '__all__'  # results_versions is not a model field, so it won't be included


class ElectionResultVersionFullSerializer(serializers.ModelSerializer):    
    class Meta:
        model = ElectionResultVersion
        fields = '__all__'


class PersistentPartyFullSerializer(serializers.ModelSerializer):
    """Full serializer for PersistentParty with nested party."""
    party = PartySerializer(read_only=True)
    
    class Meta:
        model = PersistentParty
        fields = '__all__'


class PersistentCandidateFullSerializer(serializers.ModelSerializer):
    """Full serializer for PersistentCandidate with nested person."""
    person = PersonSimpleSerializer(read_only=True)
    
    class Meta:
        model = PersistentCandidate
        fields = '__all__'


class ElectionElectorateFullSerializer(serializers.ModelSerializer):
    electorate = ElectorateSerializer(read_only=True)
    
    class Meta:
        model = ElectionElectorate
        fields = '__all__'


class ElectionPartyFullSerializer(serializers.ModelSerializer):
    persistent_party = PersistentPartyFullSerializer(read_only=True)
    
    class Meta:
        model = ElectionParty
        fields = '__all__'


class ElectionCandidateFullSerializer(serializers.ModelSerializer):
    electorate = ElectionElectorateFullSerializer(read_only=True)
    party = ElectionPartyFullSerializer(read_only=True)
    persistent_candidate = PersistentCandidateFullSerializer(read_only=True)
    
    class Meta:
        model = ElectionCandidate
        fields = '__all__'

class ResultFullSerializer(serializers.ModelSerializer):
    """Full serializer for Result with nested candidate and party."""
    candidate = ElectionCandidateFullSerializer(read_only=True)
    party = ElectionPartyFullSerializer(read_only=True)
    
    class Meta:
        model = Result
        fields = ['id', 'candidate', 'party', 'count', 'per_cent', 'list_seats', 'electorate_seats', 'total_seats']


class ResultsSetFullSerializer(serializers.ModelSerializer):
    """Full serializer for ResultsSet with fully nested context."""
    results = ResultFullSerializer(many=True, read_only=True, source='result_set')
    
    class Meta:
        model = ResultsSet
        fields = '__all__'


# Views

class PersistentDataDownloadView(views.APIView):
    """Download all persistent data (PersistentParty, PersistentCandidate, PersistentVotingPlace)."""
    
    def get(self, request):
        persistent_electorates = Electorate.objects.all()
        persistent_parties = PersistentParty.objects.all()
        persistent_candidates = PersistentCandidate.objects.all()
        persistent_voting_places = PersistentVotingPlace.objects.all()
        
        return Response({
            'persistent_electorates': ElectorateSerializer(persistent_electorates, many=True).data,
            'persistent_parties': PersistentPartySerializer(persistent_parties, many=True).data,
            'persistent_candidates': PersistentCandidateSerializer(persistent_candidates, many=True).data,
            'persistent_voting_places': PersistentVotingPlaceSerializer(persistent_voting_places, many=True).data,
        })

class ResultsVersionReferenceDataView(views.APIView):
    """Get all reference data for a given results version (electorates, voting places, candidates, and parties)."""
    
    def get(self, request, slug, version_slug):
        try:
            if version_slug == "default":
                results_version = ElectionResultVersion.objects.get(
                    election__slug=slug,
                    is_primary=True
                )
            else:
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
            'electorates': ElectionElectorateSerializer(electorates, many=True).data,
            'voting_places': ElectionVotingPlaceSerializer(voting_places, many=True).data,
            'candidates': ElectionCandidateSerializer(candidates, many=True).data,
            'parties': ElectionPartySerializer(parties, many=True).data,
        })


class ResultsVersionResultsView(views.APIView):
    """Get all results sets at electorate and national level for a given results version."""
    
    def get(self, request, slug, version_slug):
        try:
            if version_slug == "default":
                results_version = ElectionResultVersion.objects.get(
                    election__slug=slug,
                    is_primary=True
                )
            else:
                results_version = ElectionResultVersion.objects.get(
                    election__slug=slug,
                    slug=version_slug
                )
        except ElectionResultVersion.DoesNotExist:
            return Response({'error': 'Results version not found'}, status=404)
        
        results_sets = ResultsSet.objects.filter(
            results_version=results_version,
            results_level__in=['national', 'electorate']
        ).prefetch_related('result_set')
        
        return Response({
            'results_sets': ResultsSetSerializer(results_sets, many=True).data,
        })

class ResultsVersionResultsByElectorateView(views.APIView):
    """Get all results sets at voting place level for a given results version and electorate."""
    
    def get(self, request, slug, version_slug, electorate_id):
        try:
            if version_slug == "default":
                results_version = ElectionResultVersion.objects.get(
                    election__slug=slug,
                    is_primary=True
                )
            else:
                results_version = ElectionResultVersion.objects.get(
                    election__slug=slug,
                    slug=version_slug
                )
        except ElectionResultVersion.DoesNotExist:
            return Response({'error': 'Results version not found'}, status=404)
        
        try:
            electorate = ElectionElectorate.objects.get(number=electorate_id,results_version=results_version)
        except:
            try:
                electorate = ElectionElectorate.objects.get(id=electorate_id,results_version=results_version)
            except ElectionElectorate.DoesNotExist:
                return Response({'error': 'Electorate not found'}, status=404)
        
        results_sets = ResultsSet.objects.filter(
            results_version=results_version,
            results_level='voting_place',
            electorate=electorate
        ).prefetch_related('result_set')
        
        return Response({
            'results_sets': ResultsSetSerializer(results_sets, many=True).data,
        })

class ResultsVersionResultsByVotingPlaceView(views.APIView):
    """Get all results sets at voting place level for a given results version and voting place."""
    
    def get(self, request, slug, version_slug, voting_place_id):
        try:
            if version_slug == "default":
                results_version = ElectionResultVersion.objects.get(
                    election__slug=slug,
                    is_primary=True
                )
            else:
                results_version = ElectionResultVersion.objects.get(
                    election__slug=slug,
                    slug=version_slug
                )
        except ElectionResultVersion.DoesNotExist:
            return Response({'error': 'Results version not found'}, status=404)
        
        try:
            voting_place = ElectionVotingPlace.objects.get(number=voting_place_id,results_version=results_version)
        except:
            try:
                voting_place = ElectionVotingPlace.objects.get(id=voting_place_id,results_version=results_version)
            except ElectionVotingPlace.DoesNotExist:
                return Response({'error': 'Voting place not found'}, status=404)
        
        results_sets = ResultsSet.objects.filter(
            results_version=results_version,
            results_level='voting_place',
            voting_place=voting_place
        ).prefetch_related('result_set')
        
        return Response({
            'results_sets': ResultsSetSerializer(results_sets, many=True).data,
        })


class PersonElectionResultsView(views.APIView):
    """Get electorate-level election results for a given person (only is_primary results versions) with full nested context.
    Only returns results sets where the person stood in an electorate. For list-only candidates, returns election details only."""
    
    def get(self, request, slug):
        try:
            person = Person.objects.get(slug=slug)
        except Person.DoesNotExist:
            return Response({'error': 'Person not found'}, status=404)
        
        # Get PersistentCandidate for this person
        try:
            persistent_candidate = PersistentCandidate.objects.get(person=person)
        except PersistentCandidate.DoesNotExist:
            # Person has no election candidate records
            return Response({
                'elections': [],
            })
        
        # Get all ElectionCandidate instances for this PersistentCandidate
        # where results_version.is_primary=True, including both electorate and list candidates
        all_candidates = ElectionCandidate.objects.filter(
            persistent_candidate=persistent_candidate,
            results_version__is_primary=True
        ).select_related('results_version', 'results_version__election', 'electorate', 'party', 'persistent_candidate').order_by('-results_version__election__polling_date')
        
        # Separate candidates who stood in an electorate from list-only candidates
        electorate_candidates = all_candidates.filter(electorate__isnull=False)
        list_only_candidates = all_candidates.filter(electorate__isnull=True)
        
        # Get results sets for electorate candidates - only electorate level, only for the electorates they stood in
        electorate_ids = list(electorate_candidates.values_list('electorate_id', flat=True).distinct())
        
        results_sets = []
        if electorate_ids:
            results_sets_queryset = ResultsSet.objects.filter(
                results_version__in=all_candidates.values_list('results_version_id', flat=True).distinct(),
                results_level='electorate',
                electorate_id__in=electorate_ids
            ).select_related(
                'results_version',
                'results_version__election',
                'electorate',
                'electorate__electorate',
                'electorate__results_version',
                'electorate__results_version__election'
            ).prefetch_related(
                'result_set',
                'result_set__candidate',
                'result_set__candidate__electorate',
                'result_set__candidate__electorate__electorate',
                'result_set__candidate__electorate__results_version',
                'result_set__candidate__electorate__results_version__election',
                'result_set__candidate__party',
                'result_set__candidate__party__persistent_party',
                'result_set__candidate__party__persistent_party__party',
                'result_set__candidate__party__results_version',
                'result_set__candidate__party__results_version__election',
                'result_set__candidate__persistent_candidate',
                'result_set__candidate__persistent_candidate__person',
                'result_set__candidate__results_version',
                'result_set__candidate__results_version__election',
                'result_set__party',
                'result_set__party__persistent_party',
                'result_set__party__persistent_party__party',
                'result_set__party__results_version',
                'result_set__party__results_version__election'
            )
            # Group results sets by (results_version_id, electorate_id) for efficient lookup
            results_sets_dict = {}
            for rs in results_sets_queryset:
                key = (rs.results_version_id, rs.electorate_id)
                if key not in results_sets_dict:
                    results_sets_dict[key] = []
                results_sets_dict[key].append(rs)
        else:
            results_sets_dict = {}
        
        # Build response with election details and results sets
        elections_data = []
        
        # Process electorate candidates - include results sets
        for candidate in electorate_candidates:
            election = candidate.results_version.election
            # Get results sets for this candidate's electorate
            key = (candidate.results_version_id, candidate.electorate_id)
            candidate_results_sets = results_sets_dict.get(key, [])
            
            elections_data.append({
                'election': ElectionSimpleSerializer(election).data,
                'results_version': ElectionResultVersionFullSerializer(candidate.results_version).data,
                'results_sets': ResultsSetFullSerializer(candidate_results_sets, many=True).data,
                'candidate': ElectionCandidateFullSerializer(candidate).data,
            })
        
        # Process list-only candidates - just election details, no results sets
        for candidate in list_only_candidates:
            election = candidate.results_version.election
            elections_data.append({
                'election': ElectionSimpleSerializer(election).data,
                'results_version': ElectionResultVersionFullSerializer(candidate.results_version).data,
                'results_sets': [],  # No results sets for list-only candidates
                'candidate': ElectionCandidateFullSerializer(candidate).data,
            })
        
        return Response({
            'elections': elections_data,
        })
