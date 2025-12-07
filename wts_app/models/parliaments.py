"""
Parliament models.

Parliament model.
"""

from django.db import models
from django.core.validators import MinValueValidator
from .base import BaseModel
from .elections import Election


class Parliament(BaseModel):
    """
    A parliament instance or session.
    """
    number = models.IntegerField(unique=True, validators=[MinValueValidator(1)])
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    election = models.ForeignKey(Election, on_delete=models.SET_NULL, blank=True, null=True)

    def __str__(self):
        suffix = "th" if 11 <= (self.number % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(self.number % 10, "th")
        return f"{self.number}{suffix} Parliament"

    

