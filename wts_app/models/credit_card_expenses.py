from django.db import models
from .base import BaseModel
from .people import Person
from .documents import File


class CreditCardReconciliation(BaseModel):
    """
    Credit card reconciliation record linking a person to a file
    for a specific date range.
    """
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="credit_card_reconciliations"
    )
    file = models.ForeignKey(
        File,
        on_delete=models.CASCADE,
        related_name="credit_card_reconciliations"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    hidden_from_timeline = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Credit card reconciliations"
        ordering = ['-start_date', '-end_date']

    def __str__(self):
        return f"{self.person.display_name} - {self.start_date} to {self.end_date}"

