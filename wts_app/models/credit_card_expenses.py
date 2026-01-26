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
    concerns = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Credit card reconciliations"
        ordering = ['-start_date', '-end_date']

    def __str__(self):
        return f"{self.person.display_name} - {self.start_date} to {self.end_date}"


class CreditCardExpense(BaseModel):
    """
    Extracted credit card expense linked to a reconciliation.
    """
    reconciliation = models.ForeignKey(
        CreditCardReconciliation,
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    date = models.DateField()
    merchant_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    amount_nzd = models.DecimalField(max_digits=12, decimal_places=2)
    original_currency_code = models.CharField(max_length=3)
    original_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name_plural = "Credit card expenses"
        ordering = ["-date", "merchant_name"]

    def __str__(self):
        return f"{self.merchant_name} - {self.amount_nzd} NZD on {self.date}"

