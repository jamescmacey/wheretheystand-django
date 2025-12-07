"""
Election models.

Election model.
"""

from django.db import models
from .base import BaseModel
from django.utils.text import slugify
from .electorates import ElectorateBoundarySet
from .gazette import GazetteNotice

class Election(BaseModel):
    polling_date = models.DateField()
    polls_close = models.DateTimeField()
    TYPES = [("g","General"),("b", "By-election")]
    election_type = models.CharField(max_length=1,choices=TYPES,default="g")
    name = models.TextField()
    slug = models.SlugField(unique=True,blank=True,null=True)
    boundary_set = models.ForeignKey(ElectorateBoundarySet, on_delete=models.SET_NULL, blank=True, null=True)
    gazette_notices = models.ManyToManyField(GazetteNotice, blank=True)


    def save(self, *args, **kwargs):
        if not self.id or not self.slug:
            self.slug = slugify(self.name)
        super(Election, self).save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.polling_date})'

class ElectionResultVersion(BaseModel):
    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    is_primary = models.BooleanField(default=False)
    name = models.TextField()
    description = models.TextField(blank=True, null=True)
    slug = models.SlugField(blank=True,null=True)

    class Meta:
        unique_together = ('election', 'slug')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)

        # If marking this as primary, clear others for same election
        if self.is_primary:
            ElectionResultVersion.objects.filter(
                election=self.election, is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.election.name})'