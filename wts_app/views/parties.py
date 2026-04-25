"""
Party views.

Views for Party model.
"""

from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError

from ..models import Party, ParliamentaryAffiliation, PartyAffiliation, PartyLeader, Person
from .base import StandardResultsSetPagination
from .documents import SimpleFileSerializer


class PartySerializer(serializers.ModelSerializer):
    """Simple serializer for Party in nested contexts."""
    class Meta:
        model = Party
        fields = '__all__'


def _party_ids_with_current_mps(*, as_at, using: str = "sworn_date") -> set:
    """
    Party IDs that have at least one sitting MP (as at as_at) whose current
    party affiliation at that date is that party.
    """
    if using not in ("sworn_date", "elected_date"):
        raise ValueError("using must be sworn_date or elected_date")

    start_field = using
    current_parliamentary_filter = Q(**{f"{start_field}__lte": as_at}) & (
        Q(end_date__isnull=True) | Q(end_date__gte=as_at)
    )
    current_party_filter = Q(start_date__lte=as_at) & (
        Q(end_date__isnull=True) | Q(end_date__gte=as_at)
    )

    person_ids = (
        ParliamentaryAffiliation.objects.filter(current_parliamentary_filter)
        .values_list("person_id", flat=True)
        .distinct()
    )

    return set(
        PartyAffiliation.objects.filter(
            current_party_filter,
            person_id__in=person_ids,
        )
        .values_list("party_id", flat=True)
        .distinct()
    )


def _party_seat_counts_by_party_id() -> dict:
    """
    For each party, count sitting MPs (today, sworn_date) whose current party
    affiliation is that party — i.e. seats held in Parliament under that party.
    """
    as_at = timezone.now().date()
    using = "sworn_date"
    start_field = using
    current_parliamentary_filter = Q(**{f"{start_field}__lte": as_at}) & (
        Q(end_date__isnull=True) | Q(end_date__gte=as_at)
    )
    current_party_filter = Q(start_date__lte=as_at) & (
        Q(end_date__isnull=True) | Q(end_date__gte=as_at)
    )

    mp_person_ids = ParliamentaryAffiliation.objects.filter(
        current_parliamentary_filter
    ).values("person_id")

    rows = (
        PartyAffiliation.objects.filter(
            current_party_filter,
            person_id__in=mp_person_ids,
        )
        .values("party_id")
        .annotate(seats=Count("person_id", distinct=True))
    )
    return {row["party_id"]: row["seats"] for row in rows}


class PartyListSerializer(PartySerializer):
    """Party list with current parliamentary seat count (sitting MPs for this party)."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        counts = self.context.get("party_seat_counts")
        data["seat_count"] = 0 if counts is None else counts.get(instance.id, 0)
        return data


class PartyListCreateView(generics.ListCreateAPIView):
    """
    List parties that have at least one PartyAffiliation.

    Query params:
      - group (optional, default 'all'): 'all' | 'current_mps' | 'other'
          - all: every party with at least one PartyAffiliation (default).
          - current_mps: parties with at least one sitting MP (today, sworn_date)
            whose current party affiliation is this party.
          - other: all other parties with at least one PartyAffiliation.

    GET responses include ``seat_count``: sitting MPs currently affiliated with that party
    (same notion of “current” as the members-of-parliament list: today, sworn_date).
    """

    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request and self.request.method == "GET":
            return PartyListSerializer
        return PartySerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request and self.request.method == "GET":
            cache = getattr(self.request, "_party_seat_counts_cache", None)
            if cache is None:
                cache = _party_seat_counts_by_party_id()
                setattr(self.request, "_party_seat_counts_cache", cache)
            context["party_seat_counts"] = cache
        return context

    def get_queryset(self):
        group = self.request.query_params.get("group") or "all"
        if group not in ("all", "current_mps", "other"):
            raise ValidationError(
                {
                    "group": "Valid values are 'all', 'current_mps', and 'other'.",
                }
            )

        base = (
            Party.objects.filter(partyaffiliation__isnull=False)
            .distinct()
            .order_by("display_name")
        )

        if group == "all":
            return base

        as_at = timezone.now().date()
        using = "sworn_date"
        mp_party_ids = _party_ids_with_current_mps(as_at=as_at, using=using)

        if group == "current_mps":
            if not mp_party_ids:
                return Party.objects.none()
            return base.filter(id__in=mp_party_ids)

        return base.exclude(id__in=mp_party_ids) if mp_party_ids else base


class PartyLeaderPersonSerializer(serializers.ModelSerializer):
    """Same shape as PersonSimpleSerializer; defined here to avoid import cycles."""

    photo = SimpleFileSerializer(read_only=True)

    class Meta:
        model = Person
        fields = [
            "id",
            "first_name",
            "last_name",
            "display_name",
            "photo",
            "cached_description",
            "cached_colour",
            "slug",
        ]


class PartyLeaderSerializer(serializers.ModelSerializer):
    person = PartyLeaderPersonSerializer(read_only=True)

    class Meta:
        model = PartyLeader
        fields = "__all__"


class PartyDetailSerializer(PartySerializer):
    party_leaders = PartyLeaderSerializer(
        many=True, read_only=True, source="partyleader_set"
    )


class PartyRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Party.objects.prefetch_related(
        Prefetch(
            "partyleader_set",
            queryset=PartyLeader.objects.select_related("person__photo").order_by(
                "-start_date"
            ),
        )
    )
    serializer_class = PartyDetailSerializer
    lookup_field = "slug"