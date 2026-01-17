from django.db import models
from .base import BaseModel
from .elections import PersistentCandidate, Election
from .documents import File


class ElectionDonationReturn(BaseModel):
    """
    Credit card reconciliation record linking a person to a file
    for a specific date range.
    """
    candidate = models.ForeignKey(
        PersistentCandidate,
        on_delete=models.CASCADE,
        related_name="election_donation_returns"
    )
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name="election_donation_returns"
    )
    file = models.ForeignKey(
        File,
        on_delete=models.CASCADE,
        related_name="election_donation_returns"
    )
    hidden_from_timeline = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Election donation returns"
        ordering = ['-election__polling_date']

    def __str__(self):
        return f"{self.candidate.display_name} - {self.election.name}"

