"""
Bill views.

Views for Bill model.
"""

from rest_framework import generics, serializers
from ..models import Bill
from .base import StandardResultsSetPagination
from .parliaments import ParliamentSerializer
from .people import PersonSimpleSerializer


# Serializers
class BillSimpleSerializer(serializers.ModelSerializer):
    """Simple serializer for bills with minimal fields."""
    class Meta:
        model = Bill
        fields = ['id', 'name', 'ref', 'bill_type', 'status', 'introduction_date']


class BillSerializer(serializers.ModelSerializer):
    """Full serializer for bills with all fields and related objects."""
    parliaments = ParliamentSerializer(many=True, read_only=True)
    people_responsible = PersonSimpleSerializer(many=True, read_only=True)
    
    class Meta:
        model = Bill
        fields = '__all__'


# DRF Views
class BillListCreateView(generics.ListCreateAPIView):
    """List all bills or create a new bill."""
    def get_queryset(self):
        queryset = Bill.objects.prefetch_related(
            'parliaments',
            'people_responsible',
        ).all()

        # Optional ordering
        ordering = self.request.query_params.get('ordering', None)
        if ordering and ordering in ['introduction_date', '-introduction_date', 'name', '-name']:
            queryset = queryset.order_by(ordering)
        
        # Optional filtering
        bill_type = self.request.query_params.get('bill_type', None)
        if bill_type:
            queryset = queryset.filter(bill_type=bill_type)
        
        status = self.request.query_params.get('status', None)
        if status:
            queryset = queryset.filter(status=status)
        
        parliament_number = self.request.query_params.get('parliament', None)
        if parliament_number:
            queryset = queryset.filter(parliaments__number=parliament_number)
        
        person_slug = self.request.query_params.get('person', None)
        if person_slug:
            queryset = queryset.filter(people_responsible__slug=person_slug)

        return queryset.distinct()
    
    def get_serializer_class(self):
        if self.request and self.request.method == "GET":
            return BillSerializer
        return BillSerializer
    
    pagination_class = StandardResultsSetPagination


class BillRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a bill."""
    def get_queryset(self):
        return Bill.objects.prefetch_related(
            'parliaments',
            'people_responsible',
        ).all()
    
    serializer_class = BillSerializer
    lookup_field = 'pk'  # Using UUID primary key

