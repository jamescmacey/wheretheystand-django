"""
Electorate views.

Views for Electorate model.
"""

from rest_framework import generics
from rest_framework import serializers
from ..models import Electorate, ElectorateBoundarySet, ElectorateBoundary
from .documents import SimpleFileSerializer, DocumentSerializer
from .gazette import GazetteNoticeSerializer

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
    document = DocumentSerializer(read_only=True)

    class Meta:
        model = ElectorateBoundarySet
        fields = '__all__'

class ElectorateBoundarySerializer(serializers.ModelSerializer):
    shape = SimpleFileSerializer(read_only=True)
    electorate = ElectorateSerializer(read_only=True)
    boundary_set = ElectorateBoundarySetSerializer(read_only=True)

    class Meta:
        model = ElectorateBoundary
        fields = '__all__'

class ElectorateListCreateView(generics.ListCreateAPIView):
    queryset = Electorate.objects.all()
    serializer_class = ElectorateSerializer

class ElectorateRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Electorate.objects.all()
    serializer_class = ElectorateSerializer
    lookup_field = 'slug'

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

class ElectorateBoundaryRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ElectorateBoundary.objects.all()
    serializer_class = ElectorateBoundarySerializer
    lookup_field = 'pk'