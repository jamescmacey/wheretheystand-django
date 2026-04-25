"""
Electorate views.

Views for Electorate model.
"""

from rest_framework import generics
from rest_framework import serializers
from django.db.models import Prefetch
from ..models import (
    Electorate,
    ElectorateBoundarySet,
    ElectorateBoundary,
    ParliamentaryAffiliation,
    PartyAffiliation,
    Person,
    Party,
)
from .documents import FileSerializer, SimpleDocumentSerializer
from .gazette import GazetteNoticeSerializer
from .parliaments import ParliamentSerializer

class ElectorateNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Electorate
        exclude = ['replaced']

class ElectorateSerializer(serializers.ModelSerializer):
    replaced = ElectorateNestedSerializer(read_only=True)
    replacement = ElectorateNestedSerializer(read_only=True)

    class Meta:
        model = Electorate
        fields = '__all__'

class ElectorateBoundarySetSerializer(serializers.ModelSerializer):
    gazette_notice = GazetteNoticeSerializer(read_only=True)
    document = SimpleDocumentSerializer(read_only=True)

    class Meta:
        model = ElectorateBoundarySet
        fields = '__all__'

class ElectorateBoundarySerializer(serializers.ModelSerializer):
    shape = FileSerializer(read_only=True)
    simplified_shape = FileSerializer(read_only=True)
    electorate = ElectorateSerializer(read_only=True)
    boundary_set = ElectorateBoundarySetSerializer(read_only=True)

    class Meta:
        model = ElectorateBoundary
        fields = ["id", "created_at", "updated_at", "electorate", "boundary_set", "shape", "simplified_shape"]


class ElectorateHistoryPartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ["id", "slug", "display_name", "short_name", "abbreviation", "colour"]


class ElectorateHistoryPartyAffiliationSerializer(serializers.ModelSerializer):
    party = ElectorateHistoryPartySerializer(read_only=True)

    class Meta:
        model = PartyAffiliation
        fields = ["id", "start_date", "end_date", "party"]


class ElectorateHistoryPersonSerializer(serializers.ModelSerializer):
    photo = FileSerializer(read_only=True)

    class Meta:
        model = Person
        fields = ["id", "slug", "display_name", "cached_description", "cached_colour", "photo"]


class ElectorateHistoryParliamentaryAffiliationSerializer(serializers.ModelSerializer):
    person = ElectorateHistoryPersonSerializer(read_only=True)
    electorate = ElectorateNestedSerializer(read_only=True)
    parliament = ParliamentSerializer(read_only=True)
    party_affiliation = serializers.SerializerMethodField()

    class Meta:
        model = ParliamentaryAffiliation
        fields = [
            "id",
            "person",
            "electorate",
            "parliament",
            "elected_date",
            "sworn_date",
            "end_date",
            "start_reason",
            "end_reason",
            "party_affiliation",
        ]

    def get_party_affiliation(self, obj):
        # "Relevant" party at the time this parliamentary affiliation starts.
        start_date = obj.sworn_date or obj.elected_date
        if not start_date:
            return None

        party_affiliations = getattr(obj.person, "_history_party_affiliations", None)
        if party_affiliations is None:
            return None

        matched = None
        for affiliation in party_affiliations:
            if affiliation.start_date <= start_date and (
                affiliation.end_date is None or affiliation.end_date >= start_date
            ):
                matched = affiliation
                break

        if not matched:
            return None

        return ElectorateHistoryPartyAffiliationSerializer(
            matched,
            context=self.context,
        ).data

class ElectorateListCreateView(generics.ListCreateAPIView):
    queryset = Electorate.objects.all()
    serializer_class = ElectorateSerializer

class ElectorateRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Electorate.objects.all()
    serializer_class = ElectorateSerializer
    lookup_field = 'slug'


class ElectorateHistoryView(generics.ListAPIView):
    serializer_class = ElectorateHistoryParliamentaryAffiliationSerializer
    pagination_class = None

    def get_queryset(self):
        electorate_slug = self.kwargs["slug"]
        return (
            ParliamentaryAffiliation.objects.filter(electorate__slug=electorate_slug)
            .select_related("person", "person__photo", "electorate", "parliament")
            .prefetch_related(
                Prefetch(
                    "person__partyaffiliation_set",
                    queryset=PartyAffiliation.objects.select_related("party").order_by("-start_date"),
                    to_attr="_history_party_affiliations",
                )
            )
            .order_by("-sworn_date", "-elected_date")
        )

class ElectorateBoundarySetListCreateView(generics.ListCreateAPIView):
    queryset = ElectorateBoundarySet.objects.all()
    serializer_class = ElectorateBoundarySetSerializer

class ElectorateBoundarySetRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ElectorateBoundarySet.objects.all()
    serializer_class = ElectorateBoundarySetSerializer
    lookup_field = 'pk'

class ElectorateBoundaryListCreateView(generics.ListCreateAPIView):
    queryset = ElectorateBoundary.objects.all()
    serializer_class = ElectorateBoundarySerializer
    lookup_field = 'pk'

    def get_queryset(self):
        queryset = (
            ElectorateBoundary.objects.all()
            .select_related(
                "electorate",
                "electorate__replaced",
                "electorate__replacement",
                "boundary_set",
                "boundary_set__document",
                "boundary_set__gazette_notice",
                "shape",
                "simplified_shape",
                "simplified_shape__copyright_owner",
                "simplified_shape__licence_grantor",
                "simplified_shape__licence",
                "shape__copyright_owner",
                "shape__licence_grantor",
                "shape__licence",
            )
            .order_by("-boundary_set__valid_from", "-created_at")
        )
        electorate_slug = self.request.query_params.get("electorate_slug")
        if electorate_slug:
            queryset = queryset.filter(electorate__slug=electorate_slug)
        return queryset


class ElectorateBoundariesByElectorateView(generics.ListAPIView):
    serializer_class = ElectorateBoundarySerializer
    pagination_class = None

    def get_queryset(self):
        electorate_slug = self.kwargs["slug"]
        return (
            ElectorateBoundary.objects.filter(electorate__slug=electorate_slug)
            .select_related(
                "electorate",
                "electorate__replaced",
                "electorate__replacement",
                "boundary_set",
                "boundary_set__document",
                "boundary_set__gazette_notice",
                "shape",
                "simplified_shape",
                "simplified_shape__copyright_owner",
                "simplified_shape__licence_grantor",
                "simplified_shape__licence",
                "shape__copyright_owner",
                "shape__licence_grantor",
                "shape__licence",
            )
            .order_by("-boundary_set__valid_from", "-created_at")
        )

class ElectorateBoundaryRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ElectorateBoundary.objects.all()
    serializer_class = ElectorateBoundarySerializer
    lookup_field = 'pk'