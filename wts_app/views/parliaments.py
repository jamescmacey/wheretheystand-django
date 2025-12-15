from rest_framework import serializers
from ..models import Parliament

class ParliamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parliament
        fields = '__all__'
