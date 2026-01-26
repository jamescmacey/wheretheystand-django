"""
People views.

Views for Person, ParliamentaryAffiliation, PartyAffiliation, and MinisterialAffiliation.
"""

from rest_framework import generics
from rest_framework import serializers
from ..models import Person, ParliamentaryAffiliation, PartyAffiliation, MinisterialAffiliation, MinisterialPortfolio
from .documents import SimpleFileSerializer
from .base import StandardResultsSetPagination
from .parliaments import ParliamentSerializer
from .electorates import ElectorateSerializer
from .elections import ElectionSerializer
from .gazette import GazetteNoticeSerializer
from .parties import PartySerializer
from django.db.models import Q

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
    party = PartySerializer(read_only=True)
    class Meta:
        model = PartyAffiliation
        fields = '__all__'

class MinisterialPortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = MinisterialPortfolio
        fields = '__all__'

class MinisterialAffiliationSerializer(serializers.ModelSerializer):
    portfolio = MinisterialPortfolioSerializer(read_only=True)

    class Meta:
        model = MinisterialAffiliation
        fields = '__all__'
    
class PersonSimpleSerializer(serializers.ModelSerializer):
    photo = SimpleFileSerializer(read_only=True)
    
    class Meta:
        model = Person
        fields = [
            'id',
            'first_name',
            'last_name',
            'display_name',
            'photo',
            'cached_description',
            'cached_colour',
            'slug',
            'x_user',
        ]

class PersonSerializer(serializers.ModelSerializer):
    photo = SimpleFileSerializer(read_only=True)
    parliamentary_affiliations = ParliamentaryAffiliationSerializer(many=True, read_only=True, source='parliamentaryaffiliation_set')
    party_affiliations = PartyAffiliationSerializer(many=True, read_only=True, source='partyaffiliation_set')
    ministerial_affiliations = MinisterialAffiliationSerializer(many=True, read_only=True, source='ministerialaffiliation_set')

    class Meta:
        model = Person
        fields = [
            'id',
            'first_name',
            'last_name',
            'display_name',
            'photo',
            'cached_description',
            'cached_colour',
            'slug',
            'x_user',
            'parliamentary_affiliations',
            'party_affiliations',
            'ministerial_affiliations',
        ]


class ParliamentaryAffiliationFullSerializer(serializers.ModelSerializer):
    parliament = ParliamentSerializer(read_only=True)
    electorate = ElectorateSerializer(read_only=True)
    election = ElectionSerializer(read_only=True)
    gazette_notice_election = GazetteNoticeSerializer(read_only=True)
    gazette_notice_vacation = GazetteNoticeSerializer(read_only=True)
    person = PersonSimpleSerializer(read_only=True)
    class Meta:
        model = ParliamentaryAffiliation
        fields = '__all__'

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
        ).select_related('photo', 'x_user')
    
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
        ).select_related('photo', 'x_user')
    
    serializer_class = PersonSerializer
    lookup_field = 'slug'  # Or 'slug' if you use slugs

class ParliamentaryAffiliationListCreateView(generics.ListCreateAPIView):
    serializer_class = ParliamentaryAffiliationFullSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = ParliamentaryAffiliation.objects.all()
        electorate_slug = self.request.query_params.get('electorate')
        parliament_number = self.request.query_params.get('parliament')

        if electorate_slug:
            queryset = queryset.filter(electorate__slug=electorate_slug)
        if parliament_number:
            queryset = queryset.filter(parliament__number=parliament_number)

        return queryset

class ParliamentaryAffiliationRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ParliamentaryAffiliation.objects.all()
    serializer_class = ParliamentaryAffiliationFullSerializer
    lookup_field = 'pk'



class PartyAffiliationListCreateView(generics.ListCreateAPIView):
    """
    Example usage:
    GET /v2/party-affiliations/?person=alice-smith&person=bob-jones&date=2022-01-01&date=2023-02-10

    This will return party affiliations for alice-smith at 2022-01-01 and bob-jones at 2023-02-10.
    Each 'person' value should have a matching 'date' value in the same order.
    """
    serializer_class = PartyAffiliationSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        from datetime import datetime

        queryset = PartyAffiliation.objects.all()
        people_param = self.request.query_params.getlist('person')
        dates_param = self.request.query_params.getlist('date')

        # If the filter params are present and valid, filter accordingly
        if people_param and dates_param and len(people_param) == len(dates_param):
            filtered_q = Q()
            for person_slug, date_str in zip(people_param, dates_param):
                try:
                    # Validate that date_str is a valid date in YYYY-MM-DD format
                    date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    # Filter for affiliations where:
                    # - person__slug matches
                    # - start_date <= date
                    # - (end_date is null or end_date >= date)
                    q = Q(
                        person__slug=person_slug,
                        start_date__lte=date,
                    ) & (
                        (Q(end_date__isnull=True)) | Q(end_date__gte=date)
                    )
                    filtered_q |= q
                except Exception:
                    continue  # If parsing/etc fails (invalid date string), skip entry

            queryset = queryset.filter(filtered_q)
        elif people_param or dates_param:
            # If lists not the same length but one or both present, return empty queryset
            return queryset.none()

        return queryset

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

