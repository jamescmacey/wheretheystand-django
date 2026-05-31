from django.db import models
from django.core.files.storage import storages
from django.core.validators import MinValueValidator
from .base import BaseModel
from .bills import Bill


class HansardSearchResult(BaseModel):

    RESULT_TYPES = [
        ("DebateItem", "DebateItem"),
        ("__other__", "__other__"),
    ]

    RESULT_SUBTYPES = [
        ("Debate", "Debate"),
        ("Question", "Question"),
        ("Speech", "Speech"),
        ("Vote", "Vote"),
        ("__other__", "__other__"),
    ]

    RESULT_PROGRESS_TYPES = [
        ("Draft", "Draft"),
        ("Corrected", "Corrected"),
        ("Final", "Final"),
        ("__other__", "__other__"),
    ]

    """
    Here is an example of the data we are looking to store:
    {
      "id": "6166f255-af82-4e57-b311-cb76920246bf",
      "title": "Vote: Bills \u2014 Regulatory Standards Bill",
      "subtitle": "Part 3  ",
      "volumeNumber": 788,
      "sittingDate": "2025-11-11T00:00:00Z",
      "documentType": "DebateItem",
      "documentSubtype": "Vote",
      "progress": "Draft",
      "memberId": "00000000-0000-0000-0000-000000000000",
      "memberName": null,
      "sortIndex": 813,
      "portfolio": null,
      "parliamentNumber": 54,
      "types": [],
      "subtypes": [],
      "dateFrom": null,
      "dateTo": null,
      "members": [],
      "portfolios": [],
      "parentId": "9dc2acf8-9bed-4108-b610-a2dd2194f919",
      "orderByFields": []
    }
    """

    result_id = models.CharField(max_length=36, unique=True)
    result_title = models.TextField(blank=True, null=True)
    result_subtitle = models.TextField(blank=True, null=True)
    result_volume_number = models.IntegerField(blank=True, null=True, validators=[MinValueValidator(1)])
    result_sitting_date = models.DateField(blank=True, null=True)
    result_document_type = models.CharField(max_length=10, choices=RESULT_TYPES, blank=True, null=True)
    result_document_subtype = models.CharField(max_length=10, choices=RESULT_SUBTYPES, blank=True, null=True)
    result_progress = models.CharField(max_length=10, choices=RESULT_PROGRESS_TYPES, blank=True, null=True)
    result_member_id = models.CharField(max_length=36, blank=True, null=True)
    result_member_name = models.TextField(blank=True, null=True)
    result_sort_index = models.IntegerField(blank=True, null=True)
    result_portfolio = models.TextField(blank=True, null=True)
    result_parliament_number = models.IntegerField(blank=True, null=True, validators=[MinValueValidator(1)])
    result_parent_result_id = models.CharField(max_length=36, blank=True, null=True)

    retrieved_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.result_title} - {self.result_subtitle}"

class HansardDaily(BaseModel):

    DAILY_PROGRESS_TYPES = [
        ("Draft", "Complete"),
        ("Corrected", "Corrected"),
        ("Final", "Final"),
        ("__other__", "__other__"),
    ]

    def _select_storage():
        return storages['private_files']

    def _upload_to(instance, filename):
        return f"hansard/transcripts/{instance.sitting_date}.html"

    sitting_date = models.DateField(unique=True)
    transcript_file = models.FileField(upload_to=_upload_to, storage=_select_storage)
    retrieved_at = models.DateTimeField(blank=True, null=True)

    daily_content = models.TextField(blank=True, null=True)
    daily_id = models.CharField(max_length=36, blank=True, null=True)
    daily_parliament_number = models.IntegerField(blank=True, null=True, validators=[MinValueValidator(1)])
    daily_volume_number = models.IntegerField(blank=True, null=True, validators=[MinValueValidator(1)])
    daily_progress = models.CharField(max_length=10, choices=DAILY_PROGRESS_TYPES, blank=True, null=True)
    daily_title = models.TextField(blank=True, null=True)
    daily_subtitle = models.TextField(blank=True, null=True)

class HansardDebate(BaseModel):
    daily = models.ForeignKey(HansardDaily, on_delete=models.CASCADE, related_name='debates')
    debate_id = models.CharField(max_length=36, blank=True, null=True)
    debate_title = models.TextField(blank=True, null=True)
    debate_content = models.TextField(blank=True, null=True)
    debate_subtitle = models.TextField(blank=True, null=True)

class HansardBillAssocation(BaseModel):
    debate = models.ForeignKey(HansardDebate, on_delete=models.CASCADE, related_name='bill_associations')
    assocation_id = models.CharField(max_length=36, blank=True, null=True)
    bill_title = models.TextField(blank=True, null=True)
    bill_id = models.CharField(max_length=36, blank=True, null=True)
    matched_bill = models.ForeignKey(Bill, on_delete=models.SET_NULL, related_name='hansard_bill_associations', null=True, blank=True)

class HansardItem(BaseModel):
    debate = models.ForeignKey(HansardDebate, on_delete=models.CASCADE, related_name='items')

    ITEM_TYPES = [
        ("Question", "Question"),
        ("Speech", "Speech"),
        ("Vote", "Vote"),
        ("__other__", "__other__"),
    ]

    item_type = models.CharField(max_length=10, choices=ITEM_TYPES, blank=True, null=True)
    item_member_id = models.CharField(max_length=36, blank=True, null=True)
    item_electorate = models.TextField(blank=True, null=True)
    item_start_time = models.DateTimeField(blank=True, null=True)
    item_member_name = models.TextField(blank=True, null=True)
    item_id = models.CharField(max_length=36, blank=True, null=True)
    item_title = models.TextField(blank=True, null=True)
    item_content = models.TextField(blank=True, null=True)
    item_subtitle = models.TextField(blank=True, null=True)

