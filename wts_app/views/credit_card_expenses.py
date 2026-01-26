"""
Credit card expenses views.

Views for CreditCardReconciliation.
"""

from rest_framework import generics, serializers
from ..models.credit_card_expenses import CreditCardReconciliation, CreditCardExpense
from ..models.people import Person
from .base import StandardResultsSetPagination
from .documents import FileSerializer


# Serializers
class PersonSimpleSerializer(serializers.ModelSerializer):
    """Simple person serializer for nested representation."""
    class Meta:
        model = Person
        fields = ['id', 'display_name', 'slug', 'first_name', 'last_name']

class CreditCardExpenseSerializer(serializers.ModelSerializer):
    """Serializer for CreditCardExpense."""
    class Meta:
        model = CreditCardExpense
        fields = '__all__'

class CreditCardReconciliationSerializer(serializers.ModelSerializer):
    """Serializer for CreditCardReconciliation."""
    person = PersonSimpleSerializer(read_only=True)
    file = FileSerializer(read_only=True)
    expenses = CreditCardExpenseSerializer(many=True, read_only=True)
    
    class Meta:
        model = CreditCardReconciliation
        fields = '__all__'

# DRF Views
class CreditCardReconciliationListCreateView(generics.ListCreateAPIView):
    """List all credit card reconciliations or create a new one."""
    
    def get_queryset(self):
        queryset = CreditCardReconciliation.objects.select_related(
            'person', 'file'
        ).all()
        
        # Filter by person (by ID or slug)
        person_id = self.request.query_params.get('person', None)
        if person_id:
            queryset = queryset.filter(person_id=person_id)
        
        person_slug = self.request.query_params.get('person_slug', None)
        if person_slug:
            queryset = queryset.filter(person__slug=person_slug)
        
        # Filter by start_date range
        start_date_from = self.request.query_params.get('start_date_from', None)
        if start_date_from:
            queryset = queryset.filter(start_date__gte=start_date_from)
        
        start_date_to = self.request.query_params.get('start_date_to', None)
        if start_date_to:
            queryset = queryset.filter(start_date__lte=start_date_to)
        
        # Filter by end_date range
        end_date_from = self.request.query_params.get('end_date_from', None)
        if end_date_from:
            queryset = queryset.filter(end_date__gte=end_date_from)
        
        end_date_to = self.request.query_params.get('end_date_to', None)
        if end_date_to:
            queryset = queryset.filter(end_date__lte=end_date_to)
        
        # Filter by date range (checks if reconciliation overlaps with the given range)
        # This finds reconciliations that overlap with the specified date range
        date_from = self.request.query_params.get('date_from', None)
        date_to = self.request.query_params.get('date_to', None)
        
        if date_from and date_to:
            # Find reconciliations that overlap with the date range
            # A reconciliation overlaps if: start_date <= date_to AND end_date >= date_from
            queryset = queryset.filter(
                start_date__lte=date_to,
                end_date__gte=date_from
            )
        elif date_from:
            # Find reconciliations that end on or after date_from
            queryset = queryset.filter(end_date__gte=date_from)
        elif date_to:
            # Find reconciliations that start on or before date_to
            queryset = queryset.filter(start_date__lte=date_to)
        
        return queryset
    
    serializer_class = CreditCardReconciliationSerializer
    pagination_class = StandardResultsSetPagination


class CreditCardReconciliationRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a credit card reconciliation."""
    queryset = CreditCardReconciliation.objects.select_related('person', 'file', 'expenses').all()
    serializer_class = CreditCardReconciliationSerializer
    lookup_field = 'pk'

