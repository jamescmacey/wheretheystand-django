
from django.db.models import Prefetch
from rest_framework import generics, serializers

from ..models.people import FinancialInterest, FinancialInterestSnapshot
from .documents import DocumentSerializer
from .people import PersonSerializer


class FinancialInterestSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialInterest
        fields = "__all__"

class FinancialInterestSnapshotSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialInterestSnapshot
        fields = ["id", "as_at"]


class FinancialInterestSnapshotSerializer(serializers.ModelSerializer):
    document = DocumentSerializer(read_only=True)
    interests = FinancialInterestSerializer(
        source="financialinterest_set", many=True, read_only=True
    )

    class Meta:
        model = FinancialInterestSnapshot
        fields = ["id", "as_at", "document", "interests"]


class PersonFinancialInterestsView(generics.ListAPIView):
    serializer_class = FinancialInterestSnapshotSummarySerializer

    def get_queryset(self):
        slug = self.kwargs["slug"]
        return (
            FinancialInterestSnapshot.objects.filter(person__slug=slug)
            .select_related("document")
            .order_by("-as_at", "-created_at")
        )

class PersonFinancialInterestSnapshotListCreateView(generics.ListCreateAPIView):
    queryset = FinancialInterestSnapshot.objects.all()
    serializer_class = FinancialInterestSnapshotSerializer

class PersonFinancialInterestSnapshotRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FinancialInterestSnapshot.objects.all()
    serializer_class = FinancialInterestSnapshotSerializer
    lookup_field = 'pk'