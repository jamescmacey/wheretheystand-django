"""
Parliament views.

Views for Parliament model.
"""

from rest_framework import serializers, generics
from rest_framework.exceptions import ValidationError
from ..models import Parliament


class ParliamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parliament
        fields = '__all__'


class ParliamentListCreateView(generics.ListCreateAPIView):
    serializer_class = ParliamentSerializer

    def get_queryset(self):
        queryset = Parliament.objects.all().order_by("-number")
        number_gte = self.request.query_params.get("number_gte")
        if number_gte is None:
            return queryset

        try:
            min_number = int(number_gte)
        except (TypeError, ValueError):
            raise ValidationError({"number_gte": "Must be an integer."})

        return queryset.filter(number__gte=min_number)


class ParliamentRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Parliament.objects.all()
    serializer_class = ParliamentSerializer
    lookup_field = "number"
