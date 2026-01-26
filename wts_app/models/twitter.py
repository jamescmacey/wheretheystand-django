"""
Twitter models.

Models for Twitter users and their metrics snapshots.
"""

from django.db import models

from .base import BaseModel


class TwitterUser(BaseModel):
    user_id = models.TextField()
    name = models.TextField()
    username = models.TextField()
    description = models.TextField(blank=True, null=True)
    protected = models.BooleanField(default=False)
    verified = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.username} ({self.name})"


class TwitterMetrics(BaseModel):
    user = models.ForeignKey(TwitterUser, on_delete=models.CASCADE)
    followers_count = models.IntegerField(blank=True, null=True)
    following_count = models.IntegerField(blank=True, null=True)
    tweet_count = models.IntegerField(blank=True, null=True)
    listed_count = models.IntegerField(blank=True, null=True)
    measured_at = models.DateTimeField(blank=True, null=True)

    def __str__(self) -> str:
        if self.measured_at:
            return f"{self.user.username} metrics @ {self.measured_at.isoformat()}"
        return f"{self.user.username} metrics"
