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
class PersonSerializer(serializers.ModelSerializer):
    photo = SimpleFileSerializer(read_only=True)
    
    class Meta:
        model = Person
        fields = '__all__'

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

# DRF Views
class PersonListCreateView(generics.ListCreateAPIView):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = StandardResultsSetPagination

class PersonRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Person.objects.all()
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

