"""
Party views.

Views for Party model.
"""

from rest_framework import serializers
from ..models import Party

class PartySerializer(serializers.ModelSerializer):
    """Simple serializer for Party in nested contexts."""
    class Meta:
        model = Party
        fields = '__all__'