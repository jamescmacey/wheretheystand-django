"""
Election results views.

Views for election results data including persistent data, reference data, and elections.
"""

from django.db.models import Prefetch
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


# Serializers
#
# These serialise the canonical election results contract. The same JSON is
# served by this API, written to the R2 snapshots, and produced by the client's
# Firestore adapter, so that components never need to know which transport
# delivered a results set.
#
# Election-scoped entities (electorates, parties, candidates, voting places) are
# referenced by their Electoral Commission ``number``, never by primary key.
# Those integers are what Firestore results carry, and the worker cannot safely
# re-key them mid-event. They are unique only within a results version, so every
# consumer must scope lookups to one.
#
# Persistent entities are referenced by primary key, because they exist to
# survive across elections and therefore have no Electoral Commission number.


class NumberRelatedField(serializers.SlugRelatedField):
    """A related entity rendered as its Electoral Commission number.

    ``SlugRelatedField`` rather than ``IntegerField(source='x.number')``: the
    latter is not null safe across a nullable foreign key, and would silently
    drop the key from the payload instead of emitting null.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault('slug_field', 'number')
        kwargs.setdefault('read_only', True)
        super().__init__(**kwargs)


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


class PersistentElectorateSerializer(serializers.ModelSerializer):
    """A lean electorate for the persistent data payload.

    The general ElectorateSerializer nests the electorates this one replaced and
    was replaced by, which is dead weight in a payload that already carries every
    electorate and is inlined into the server-rendered page.
    """

    class Meta:
        model = Electorate
        fields = ['id', 'name', 'slug', 'region', 'electorate_type', 'status',
                  'legacy_id']


class ElectionElectorateSerializer(serializers.ModelSerializer):
    """An electorate as it stood at one election, keyed by its number."""
    persistent_electorate = serializers.PrimaryKeyRelatedField(
        source='electorate', read_only=True)

    class Meta:
        model = ElectionElectorate
        fields = ['number', 'name', 'accepting_candidate_votes',
                  'persistent_electorate', 'id']


class ElectionPartySerializer(serializers.ModelSerializer):
    """A party as it contested one election, keyed by its number."""
    persistent_party = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ElectionParty
        fields = ['number', 'name', 'short_name', 'abbreviation', 'registered',
                  'persistent_party', 'id']


class ElectionCandidateSerializer(serializers.ModelSerializer):
    """A candidate at one election, keyed by number."""
    electorate = NumberRelatedField()
    party = NumberRelatedField()
    persistent_candidate = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ElectionCandidate
        fields = ['number', 'name', 'electorate', 'party', 'list_pos', 'is_dead',
                  'persistent_candidate', 'id']


class ElectionVotingPlaceSerializer(serializers.ModelSerializer):
    """A voting place at one election, keyed by number."""
    physical_electorate = NumberRelatedField()
    persistent_voting_place = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ElectionVotingPlace
        fields = ['number', 'physical_electorate', 'address', 'latitude',
                  'longitude', 'persistent_voting_place', 'id']


class ResultSerializer(serializers.ModelSerializer):
    """One tally line within a results set."""
    candidate = NumberRelatedField()
    party = NumberRelatedField()

    class Meta:
        model = Result
        fields = ['candidate', 'party', 'count', 'per_cent', 'list_seats',
                  'electorate_seats', 'total_seats']


class ResultsSetSerializer(serializers.ModelSerializer):
    """A results set in the canonical cross-transport shape."""
    key = serializers.CharField(source='canonical_key', read_only=True)
    electorate = NumberRelatedField()
    voting_place = NumberRelatedField()
    voting_place_electorate = serializers.SerializerMethodField()
    statistics = serializers.SerializerMethodField()
    updated_timestamp = serializers.SerializerMethodField()
    results_type = serializers.SerializerMethodField()
    transport = serializers.SerializerMethodField()
    source_id = serializers.CharField(source='id', read_only=True)
    results = ResultSerializer(many=True, read_only=True, source='result_set')

    class Meta:
        model = ResultsSet
        fields = ['key', 'results_level', 'results_category', 'results_type',
                  'electorate', 'voting_place', 'voting_place_electorate',
                  'result_number', 'informals', 'unknowns', 'refused',
                  'sample_size', 'is_final', 'updated', 'updated_timestamp',
                  'parsed', 'received', 'statistics', 'results',
                  'transport', 'source_id']

    def get_voting_place_electorate(self, obj):
        """The electorate a voting place physically sits in.

        A voting place can issue votes for electorates other than the one it
        stands in, so this is distinct from ``electorate``. A method field
        rather than a source traversal: a read-only related field whose parent
        is null is dropped from the payload rather than rendered as null, and
        the contract requires every key to be present.
        """
        if obj.voting_place_id is None:
            return None
        physical = obj.voting_place.physical_electorate
        return physical.number if physical else None

    def get_statistics(self, obj):
        return obj.statistics_payload()

    def get_updated_timestamp(self, obj):
        """Epoch seconds, used by clients to reject out-of-order updates."""
        return obj.updated.timestamp() if obj.updated else None

    def get_results_type(self, obj):
        # Only actual results are stored; the field exists so that the shape
        # matches Firestore, which also carries projections.
        return 'actual'

    def get_transport(self, obj):
        return 'snapshot'


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
            'persistent_electorates': PersistentElectorateSerializer(persistent_electorates, many=True).data,
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
        candidates = ElectionCandidate.objects.filter(
            results_version=results_version).select_related('electorate', 'party')
        parties = ElectionParty.objects.filter(results_version=results_version)

        payload = {
            'electorates': ElectionElectorateSerializer(electorates, many=True).data,
            'candidates': ElectionCandidateSerializer(candidates, many=True).data,
            'parties': ElectionPartySerializer(parties, many=True).data,
            'voting_places': [],
        }

        # Voting places are excluded by default: there are several thousand per
        # general election, which dwarfs the rest of the payload and is only
        # needed once somebody opens the voting place views.
        if request.query_params.get('include') == 'voting_places':
            voting_places = ElectionVotingPlace.objects.filter(
                results_version=results_version).select_related('physical_electorate')
            payload['voting_places'] = ElectionVotingPlaceSerializer(
                voting_places, many=True).data

        return Response(payload)


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
        ).select_related(
            'electorate', 'voting_place', 'voting_place__physical_electorate'
        ).prefetch_related(
            Prefetch('result_set',
                     queryset=Result.objects.select_related('candidate', 'party'))
        )
        
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
        ).select_related(
            'electorate', 'voting_place', 'voting_place__physical_electorate'
        ).prefetch_related(
            Prefetch('result_set',
                     queryset=Result.objects.select_related('candidate', 'party'))
        )
        
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
        ).select_related(
            'electorate', 'voting_place', 'voting_place__physical_electorate'
        ).prefetch_related(
            Prefetch('result_set',
                     queryset=Result.objects.select_related('candidate', 'party'))
        )
        
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
