from rest_framework import generics
from rest_framework import serializers
from ..models import GazetteNotice
from .documents import FileSerializer

class GazetteNoticeSerializer(serializers.ModelSerializer):
    file = FileSerializer(read_only=True)
    class Meta:
        model = GazetteNotice
        fields = '__all__'

class GazetteNoticeListCreateView(generics.ListCreateAPIView):
    queryset = GazetteNotice.objects.all()
    serializer_class = GazetteNoticeSerializer

class GazetteNoticeRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = GazetteNotice.objects.all()
    serializer_class = GazetteNoticeSerializer
    lookup_field = 'number'