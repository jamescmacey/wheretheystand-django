"""
X views.

Views for XUser and XMetrics models.
"""

from rest_framework import generics, serializers

from ..models import XMetrics, XUser
from .base import StandardResultsSetPagination


class XUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = XUser
        fields = '__all__'


class XMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = XMetrics
        fields = '__all__'


class XUserListCreateView(generics.ListCreateAPIView):
    serializer_class = XUserSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = XUser.objects.all()
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        username = self.request.query_params.get('username')
        if username:
            queryset = queryset.filter(username=username)
        return queryset


class XUserRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = XUser.objects.all()
    serializer_class = XUserSerializer
    lookup_field = 'pk'


class XMetricsListCreateView(generics.ListCreateAPIView):
    serializer_class = XMetricsSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = XMetrics.objects.select_related('user').all()
        user_id = self.request.query_params.get('user')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        username = self.request.query_params.get('username')
        if username:
            queryset = queryset.filter(user__username=username)
        return queryset


class XMetricsRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = XMetricsSerializer
    lookup_field = 'pk'

    def get_queryset(self):
        return XMetrics.objects.select_related('user').all()
