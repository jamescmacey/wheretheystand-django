"""
Election views.

Views for Election model.
"""

from rest_framework import generics
from rest_framework import serializers
from ..models import Election
from .electorates import ElectorateBoundarySetSerializer
from .gazette import GazetteNoticeSerializer

class ElectionSerializer(serializers.ModelSerializer):
    boundary_set = ElectorateBoundarySetSerializer(read_only=True)
    gazette_notices = GazetteNoticeSerializer(read_only=True, many=True)
    
    class Meta:
        model = Election
        fields = '__all__'

class ElectionListCreateView(generics.ListCreateAPIView):
    queryset = Election.objects.all()
    serializer_class = ElectionSerializer

class ElectionRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Election.objects.all()
    serializer_class = ElectionSerializer
    lookup_field = 'slug'