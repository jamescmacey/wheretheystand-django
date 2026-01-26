"""
Twitter views.

Views for TwitterUser and TwitterMetrics models.
"""

from rest_framework import generics, serializers

from ..models import TwitterMetrics, TwitterUser
from .base import StandardResultsSetPagination


class TwitterUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = TwitterUser
        fields = '__all__'


class TwitterMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TwitterMetrics
        fields = '__all__'


class TwitterUserListCreateView(generics.ListCreateAPIView):
    serializer_class = TwitterUserSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = TwitterUser.objects.all()
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        username = self.request.query_params.get('username')
        if username:
            queryset = queryset.filter(username=username)
        return queryset


class TwitterUserRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = TwitterUser.objects.all()
    serializer_class = TwitterUserSerializer
    lookup_field = 'pk'


class TwitterMetricsListCreateView(generics.ListCreateAPIView):
    serializer_class = TwitterMetricsSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = TwitterMetrics.objects.select_related('user').all()
        user_id = self.request.query_params.get('user')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        username = self.request.query_params.get('username')
        if username:
            queryset = queryset.filter(user__username=username)
        return queryset


class TwitterMetricsRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TwitterMetricsSerializer
    lookup_field = 'pk'

    def get_queryset(self):
        return TwitterMetrics.objects.select_related('user').all()
