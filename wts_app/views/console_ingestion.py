"""Lightweight admin-console reference data for workbook ingestion."""

from django.db.models import Q
from rest_framework import generics, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser

from wts_app.models import Person
from wts_app.models.documents import CopyrightParty, Licence
from wts_app.models.people import MinisterialPortfolio


class ConsolePersonPickerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ("id", "display_name")


class ConsoleLicencePickerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Licence
        fields = ("id", "name")


class ConsoleCopyrightPartyPickerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CopyrightParty
        fields = ("id", "name")


class ConsolePersonPickerListView(generics.ListAPIView):
    """All people (id + display_name) for searchable console pickers."""

    serializer_class = ConsolePersonPickerSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    pagination_class = None

    def get_queryset(self):
        qs = Person.objects.order_by("display_name")
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        return qs


class ConsoleLicencePickerListView(generics.ListAPIView):
    serializer_class = ConsoleLicencePickerSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    pagination_class = None

    def get_queryset(self):
        qs = Licence.objects.order_by("name")
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class ConsoleMinisterialPortfolioPickerSerializer(serializers.ModelSerializer):
    class Meta:
        model = MinisterialPortfolio
        fields = ("id", "name")


class ConsoleMinisterialPortfolioPickerListView(generics.ListAPIView):
    """Ministerial portfolios for searchable console pickers."""

    serializer_class = ConsoleMinisterialPortfolioPickerSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    pagination_class = None

    def get_queryset(self):
        qs = MinisterialPortfolio.objects.order_by("name")
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class ConsoleCopyrightPartyPickerListView(generics.ListAPIView):
    serializer_class = ConsoleCopyrightPartyPickerSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    pagination_class = None

    def get_queryset(self):
        qs = CopyrightParty.objects.order_by("name")
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs
