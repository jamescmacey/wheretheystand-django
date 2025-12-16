"""
People views.

Views for Person, ParliamentaryAffiliation, PartyAffiliation, and MinisterialAffiliation.
"""

from rest_framework import generics
from rest_framework import serializers
from ..models import Person, ParliamentaryAffiliation, PartyAffiliation, MinisterialAffiliation
from .documents import SimpleFileSerializer
from .base import StandardResultsSetPagination
from .parliaments import ParliamentSerializer
from .electorates import ElectorateSerializer
from .elections import ElectionSerializer
from .gazette import GazetteNoticeSerializer

# Serializers
class ParliamentaryAffiliationSerializer(serializers.ModelSerializer):
    parliament = ParliamentSerializer(read_only=True)
    electorate = ElectorateSerializer(read_only=True)
    election = ElectionSerializer(read_only=True)
    gazette_notice_election = GazetteNoticeSerializer(read_only=True)
    gazette_notice_vacation = GazetteNoticeSerializer(read_only=True)
    class Meta:
        model = ParliamentaryAffiliation
        fields = '__all__'

class PartyAffiliationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartyAffiliation
        fields = '__all__'

class MinisterialAffiliationSerializer(serializers.ModelSerializer):
    class Meta:
        model = MinisterialAffiliation
        fields = '__all__'
    
class PersonSimpleSerializer(serializers.ModelSerializer):
    photo = SimpleFileSerializer(read_only=True)
    
    class Meta:
        model = Person
        fields = ['id', 'first_name', 'last_name', 'display_name', 'photo', 'cached_description', 'cached_colour']

class PersonSerializer(serializers.ModelSerializer):
    photo = SimpleFileSerializer(read_only=True)
    parliamentary_affiliations = ParliamentaryAffiliationSerializer(many=True, read_only=True, source='parliamentaryaffiliation_set')
    party_affiliations = PartyAffiliationSerializer(many=True, read_only=True, source='partyaffiliation_set')
    ministerial_affiliations = MinisterialAffiliationSerializer(many=True, read_only=True, source='ministerialaffiliation_set')

    class Meta:
        model = Person
        fields = ['id', 'first_name', 'last_name', 'display_name', 'photo', 'cached_description', 'cached_colour', 'parliamentary_affiliations', 'party_affiliations', 'ministerial_affiliations']


# DRF Views
class PersonListCreateView(generics.ListCreateAPIView):
    def get_queryset(self):
        return Person.objects.prefetch_related(
            'parliamentaryaffiliation_set__parliament',
            'parliamentaryaffiliation_set__electorate',
            'parliamentaryaffiliation_set__election',
            'parliamentaryaffiliation_set__gazette_notice_election',
            'parliamentaryaffiliation_set__gazette_notice_vacation',
            'partyaffiliation_set__party',
            'ministerialaffiliation_set__portfolio',
        ).select_related('photo')
    
    def get_serializer_class(self):
        if self.request and self.request.method == "GET":
            return PersonSerializer
        return PersonSerializer
    pagination_class = StandardResultsSetPagination

class PersonRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    def get_queryset(self):
        return Person.objects.prefetch_related(
            'parliamentaryaffiliation_set__parliament',
            'parliamentaryaffiliation_set__electorate',
            'parliamentaryaffiliation_set__election',
            'parliamentaryaffiliation_set__gazette_notice_election',
            'parliamentaryaffiliation_set__gazette_notice_vacation',
            'partyaffiliation_set__party',
            'ministerialaffiliation_set__portfolio',
        ).select_related('photo')
    
    serializer_class = PersonSerializer
    lookup_field = 'slug'  # Or 'slug' if you use slugs

class ParliamentaryAffiliationListCreateView(generics.ListCreateAPIView):
    queryset = ParliamentaryAffiliation.objects.all()
    serializer_class = ParliamentaryAffiliationSerializer
    pagination_class = StandardResultsSetPagination

class ParliamentaryAffiliationRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ParliamentaryAffiliation.objects.all()
    serializer_class = ParliamentaryAffiliationSerializer
    lookup_field = 'pk'

class PartyAffiliationListCreateView(generics.ListCreateAPIView):
    queryset = PartyAffiliation.objects.all()
    serializer_class = PartyAffiliationSerializer

class PartyAffiliationRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PartyAffiliation.objects.all()
    serializer_class = PartyAffiliationSerializer
    lookup_field = 'pk'

class MinisterialAffiliationListCreateView(generics.ListCreateAPIView):
    queryset = MinisterialAffiliation.objects.all()
    serializer_class = MinisterialAffiliationSerializer

class MinisterialAffiliationRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = MinisterialAffiliation.objects.all()
    serializer_class = MinisterialAffiliationSerializer
    lookup_field = 'pk'

