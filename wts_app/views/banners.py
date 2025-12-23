from django.utils import timezone
from django.db.models import Q
from rest_framework import generics
from rest_framework import serializers
from ..models import Banner


class BannerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Banner
        fields = '__all__'


class BannerListCreateView(generics.ListCreateAPIView):
    serializer_class = BannerSerializer
    
    def get_queryset(self):
        """
        Filter banners to only show those currently meant to be displayed.
        A banner is currently active if:
        - display_start <= now
        - display_end is None (indefinite) OR display_end >= now
        
        If the user is authenticated and staff, they can request all banners
        by adding ?all=true to the query string.
        """
        # Check if user requested all banners and is authenticated staff
        request_all = self.request.query_params.get('all', '').lower() == 'true'
        if request_all:
            if self.request.user.is_authenticated and self.request.user.is_staff:
                return Banner.objects.all()
            # If not authenticated/staff, ignore the parameter and return filtered results
        
        # Default: filter to only active banners
        now = timezone.now()
        return Banner.objects.filter(
            display_start__lte=now
        ).filter(
            Q(display_end__isnull=True) | Q(display_end__gte=now)
        )


class BannerRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Banner.objects.all()
    serializer_class = BannerSerializer

