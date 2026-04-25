"""
Bill views.

Views for Bill model.
"""

from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
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
        fields = ['id', 'name', 'ref', 'bill_type', 'status', 'introduction_date', 'last_activity_date']


class BillSerializer(serializers.ModelSerializer):
    """Full serializer for bills with all fields and related objects."""
    parliaments = ParliamentSerializer(many=True, read_only=True)
    people_responsible = PersonSimpleSerializer(many=True, read_only=True)
    
    class Meta:
        model = Bill
        fields = '__all__'


def _truthy_param(value):
    if value is None:
        return False
    return str(value).lower() in ('1', 'true', 'yes')


def _parse_bill_types(request):
    """Return a list of bill type codes from repeated or comma-separated query params."""
    raw = request.query_params.getlist('bill_types')
    if raw:
        return [t.strip() for part in raw for t in part.split(',') if t.strip()]
    single = request.query_params.get('bill_types')
    if single:
        return [t.strip() for t in single.split(',') if t.strip()]
    return []


VALID_BILL_TYPES = {'government', 'members', 'private', 'local'}


# DRF Views
class BillListCreateView(generics.ListCreateAPIView):
    """List all bills or create a new bill."""
    def get_queryset(self):
        queryset = Bill.objects.prefetch_related(
            'parliaments',
            'people_responsible',
        ).all()

        search = (self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        bill_types = [t for t in _parse_bill_types(self.request) if t in VALID_BILL_TYPES]
        if bill_types:
            queryset = queryset.filter(bill_type__in=bill_types)
        else:
            bill_type = self.request.query_params.get('bill_type', None)
            if bill_type and bill_type in VALID_BILL_TYPES:
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

        if _truthy_param(self.request.query_params.get('urgency_used')):
            queryset = queryset.filter(urgency_used=True)

        if _truthy_param(self.request.query_params.get('extended_sittings_used')):
            queryset = queryset.filter(extended_sittings_used=True)

        if _truthy_param(self.request.query_params.get('open_submissions')):
            queryset = queryset.filter(submissions_due_date__gte=timezone.now().date())

        voting_methods = self.request.query_params.get('voting_methods')
        if voting_methods in ('personal', 'party'):
            queryset = queryset.filter(voting_methods=voting_methods)

        ordering = self.request.query_params.get('ordering', '-last_activity_date')
        allowed_simple = [
            'introduction_date',
            '-introduction_date',
            'name',
            '-name',
            'last_activity_date',
            '-last_activity_date',
        ]
        if ordering in allowed_simple:
            queryset = queryset.order_by(ordering)
        elif ordering in ('progress_stage', '-progress_stage'):
            queryset = queryset.annotate(
                progress_stage=Case(
                    When(royal_assent_date__isnull=False, then=Value(6)),
                    When(third_reading_date__isnull=False, then=Value(5)),
                    When(whole_house_date__isnull=False, then=Value(4)),
                    When(second_reading_date__isnull=False, then=Value(3)),
                    When(first_reading_date__isnull=False, then=Value(2)),
                    When(introduction_date__isnull=False, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
            ).order_by(ordering)
        else:
            queryset = queryset.order_by('-last_activity_date')

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

