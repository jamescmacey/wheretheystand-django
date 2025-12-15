"""
Documents views.

Views for Category, CopyrightParty, Licence, Document, File, and DocumentCollection.
"""

from rest_framework import generics
from rest_framework import serializers
from ..models.documents import Category, CopyrightParty, Licence, Document, File, DocumentCollection

# Serializers
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'

class CopyrightPartySerializer(serializers.ModelSerializer):
    class Meta:
        model = CopyrightParty
        fields = '__all__'

class LicenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Licence
        fields = '__all__'


class FileSerializer(serializers.ModelSerializer):
    copyright_owner = CopyrightPartySerializer(read_only=True)
    licence_grantor = CopyrightPartySerializer(read_only=True)
    licence = LicenceSerializer(read_only=True)

    class Meta:
        model = File
        fields = '__all__'

class SimpleFileSerializer(serializers.ModelSerializer):
    copyright_owner = CopyrightPartySerializer(read_only=True)
    licence_grantor = CopyrightPartySerializer(read_only=True)
    licence = LicenceSerializer(read_only=True)

    class Meta:
        model = File
        fields = ['id', 'file', 'copyright_owner', 'licence_grantor', 'licence']

class DocumentSerializer(serializers.ModelSerializer):
    files = FileSerializer(many=True, read_only=True)
    class Meta:
        model = Document
        fields = ['id', 'name', 'description', 'files']

class DocumentCollectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentCollection
        fields = '__all__'

# DRF Views
class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

class CategoryRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_field = 'slug'

class CopyrightPartyListCreateView(generics.ListCreateAPIView):
    queryset = CopyrightParty.objects.all()
    serializer_class = CopyrightPartySerializer

class CopyrightPartyRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = CopyrightParty.objects.all()
    serializer_class = CopyrightPartySerializer
    lookup_field = 'pk'

class LicenceListCreateView(generics.ListCreateAPIView):
    queryset = Licence.objects.all()
    serializer_class = LicenceSerializer

class LicenceRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Licence.objects.all()
    serializer_class = LicenceSerializer
    lookup_field = 'pk'

class DocumentListCreateView(generics.ListCreateAPIView):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

class DocumentRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    lookup_field = 'slug'

class FileListCreateView(generics.ListCreateAPIView):
    queryset = File.objects.all()
    serializer_class = FileSerializer

class FileRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = File.objects.all()
    serializer_class = FileSerializer
    lookup_field = 'pk'

class DocumentCollectionListCreateView(generics.ListCreateAPIView):
    queryset = DocumentCollection.objects.all()
    serializer_class = DocumentCollectionSerializer

class DocumentCollectionRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = DocumentCollection.objects.all()
    serializer_class = DocumentCollectionSerializer
    lookup_field = 'pk'

