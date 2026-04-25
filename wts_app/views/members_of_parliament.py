from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from django.db.models import Q, Prefetch

from ..models import Person, ParliamentaryAffiliation, PartyAffiliation
from .people import ParliamentaryAffiliationSerializer
from .base import MPListPagination
from .parties import PartySerializer


class PartyAffiliationWithPartySerializer(serializers.ModelSerializer):
    """PartyAffiliation serializer that includes party details."""
    party = PartySerializer(read_only=True)
    
    class Meta:
        model = PartyAffiliation
        fields = '__all__'


class MPSerializer(serializers.ModelSerializer):
    """Serializer for MP list view - Person with current affiliations."""
    photo = serializers.SerializerMethodField()
    parliamentary_affiliation = serializers.SerializerMethodField()
    party_affiliation = serializers.SerializerMethodField()
    
    def get_photo(self, obj):
        """Get photo using SimpleFileSerializer."""
        from .documents import SimpleFileSerializer
        if obj.photo:
            return SimpleFileSerializer(obj.photo).data
        return None
    
    def get_parliamentary_affiliation(self, obj):
        """Get the current ParliamentaryAffiliation at the as_at date."""
        # Get the as_at date from the request context
        as_at = self.context.get('as_at')
        using = self.context.get('using', 'sworn_date')
        
        if not as_at:
            return None
        
        # Get the prefetched current parliamentary affiliation
        # The prefetch should have filtered to only current affiliations
        current_affiliations = getattr(obj, '_current_parliamentary_affiliations', [])
        if current_affiliations:
            return ParliamentaryAffiliationSerializer(current_affiliations[0], context=self.context).data
        return None
    
    def get_party_affiliation(self, obj):
        """Get the current PartyAffiliation at the as_at date."""
        # Get the as_at date from the request context
        as_at = self.context.get('as_at')
        
        if not as_at:
            return None
        
        # Get the prefetched current party affiliation
        current_affiliations = getattr(obj, '_current_party_affiliations', [])
        if current_affiliations:
            return PartyAffiliationWithPartySerializer(current_affiliations[0], context=self.context).data
        return None
    
    class Meta:
        model = Person
        fields = '__all__'


class MPListView(generics.ListAPIView):
    serializer_class = MPSerializer
    pagination_class = MPListPagination

    def get_queryset(self):
        """
        Supports query params:
          - as_at (YYYY-MM-DD): date to check membership (default: today)
          - using (sworn_date|elected_date): which date field to use for membership period (default: sworn_date)
          - party_slug (optional): only return MPs whose current party affiliation
            at as_at date has this party slug.
        """
        # Get query params
        from django.utils.dateparse import parse_date

        request = self.request
        today = timezone.now().date()

        as_at_param = request.query_params.get("as_at")
        using = request.query_params.get("using", "sworn_date")
        party_slug = request.query_params.get("party_slug")
        if as_at_param:
            as_at = parse_date(as_at_param)
            if as_at is None:
                raise ValidationError({"as_at": "Invalid date format. Use YYYY-MM-DD."})
        else:
            as_at = today

        if using not in ["sworn_date", "elected_date"]:
            raise ValidationError({"using": "Valid values are 'sworn_date' or 'elected_date'."})

        start_field = using
        
        # Filter for current ParliamentaryAffiliation at as_at date
        current_parliamentary_filter = Q(**{f"{start_field}__lte": as_at}) & (
            Q(end_date__isnull=True) | Q(end_date__gte=as_at)
        )
        
        # Filter for current PartyAffiliation at as_at date
        current_party_filter = Q(start_date__lte=as_at) & (
            Q(end_date__isnull=True) | Q(end_date__gte=as_at)
        )
        
        # Prefetch current parliamentary affiliations with all related objects
        # Note: We can't use [:1] in Prefetch, so we'll get all current ones and take first in serializer
        parliamentary_prefetch = Prefetch(
            'parliamentaryaffiliation_set',
            queryset=ParliamentaryAffiliation.objects.filter(
                Q(**{f"{start_field}__lte": as_at}) & (Q(end_date__isnull=True) | Q(end_date__gte=as_at))
            )
            .select_related('parliament', 'electorate', 'election', 'gazette_notice_election', 'gazette_notice_vacation')
            .order_by(f'-{start_field}'),
            to_attr='_current_parliamentary_affiliations'
        )
        
        # Prefetch current party affiliations with party details
        party_filter = Q(start_date__lte=as_at) & (Q(end_date__isnull=True) | Q(end_date__gte=as_at))
        if party_slug:
            party_filter &= Q(party__slug=party_slug)

        party_prefetch = Prefetch(
            'partyaffiliation_set',
            queryset=PartyAffiliation.objects.filter(party_filter)
            .select_related('party')
            .order_by('-start_date'),
            to_attr='_current_party_affiliations'
        )
        
        # Query for people who are MPs at as_at.
        parliamentary_person_ids = ParliamentaryAffiliation.objects.filter(
            current_parliamentary_filter
        ).values_list('person_id', flat=True).distinct()

        # Optionally constrain to one current party by slug.
        if party_slug:
            party_person_ids = PartyAffiliation.objects.filter(
                party_filter
            ).values_list('person_id', flat=True).distinct()
            person_ids = parliamentary_person_ids.filter(person_id__in=party_person_ids)
        else:
            person_ids = parliamentary_person_ids
        
        # Get Person objects with prefetched affiliations
        queryset = Person.objects.filter(id__in=person_ids)\
            .order_by('last_name', 'first_name')\
            .prefetch_related(parliamentary_prefetch, party_prefetch)\
            .select_related('photo')
        
        return queryset
    
    def get_serializer_context(self):
        """Add as_at and using to serializer context."""
        context = super().get_serializer_context()
        from django.utils.dateparse import parse_date
        
        request = self.request
        today = timezone.now().date()
        
        as_at_param = request.query_params.get("as_at")
        using = request.query_params.get("using", "sworn_date")
        
        if as_at_param:
            as_at = parse_date(as_at_param)
            if as_at is None:
                as_at = today
        else:
            as_at = today
        
        context['as_at'] = as_at
        context['using'] = using
        return context
