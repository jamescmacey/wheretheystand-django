"""
Electorate models.

Electorate model.
"""

from django.db import models
from .base import BaseModel
from .documents import File, Document
from .gazette import GazetteNotice
from django.core.validators import MinValueValidator

class Electorate(BaseModel):
    """
    An electorate (e.g., voting district).
    """
    name = models.TextField()
    TYPES = [("general","General"),("maori", "Māori")]
    TYPES_LOOKUP = dict(TYPES)
    electorate_type = models.CharField(max_length=10,choices=TYPES,default="general")
    STATUSES = [("current","Current"),("retiring", "Retiring"),("new", "New"),("former", "Former"),("renamed","Renamed")]
    STATUSES_LOOKUP = dict(STATUSES)
    status = models.CharField(max_length=10,choices=STATUSES,default="current")
    replaced = models.ForeignKey('self',on_delete=models.SET_NULL, blank=True, null=True, related_name="replacement")

    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    valid_from = models.DateField()
    valid_to = models.DateField(blank=True,null=True)

    region = models.TextField()

    slug = models.SlugField(unique=True,blank=True,null=True)

    def save(self, *args, **kwargs):
        if not self.id or not self.slug:
            self.slug = slugify(self.name)
        super(Electorate, self).save(*args, **kwargs)

    def __str__(self):
        return self.name

class ElectorateBoundarySet(BaseModel):
    gazette_notice = models.ForeignKey(GazetteNotice, on_delete=models.SET_NULL, blank=True, null=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="electorate_boundary_sets")

class ElectorateBoundary(BaseModel):
    electorate = models.ForeignKey(Electorate, on_delete=models.CASCADE)
    boundary_set = models.ForeignKey(ElectorateBoundarySet, on_delete=models.CASCADE)
    shape = models.ForeignKey(File, on_delete=models.CASCADE, related_name="electorate_boundaries")