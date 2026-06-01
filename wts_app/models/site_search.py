from random import choice
from .base import UUIDPrimaryKeyMixin
from django.db import models

class SiteSearch(UUIDPrimaryKeyMixin):
    """
    An object that is synced to Algolia for site search.
    """
    TYPES = [
        ("person", "Person"),
        ("party", "Party"),
        ("electorate", "Electorate"),
        ("bill", "Bill"),
        ("vote", "Vote"),
        ("hansard", "Hansard"),
        ("gazette", "Gazette"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=255, choices=TYPES)
    data = models.JSONField()

    @property
    def id_as_str(self):
        return str(self.id)

    def __str__(self):
        return f"{self.type}: {self.name}"