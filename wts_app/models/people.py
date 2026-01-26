"""
People models.

Person and PersonNameHistory models.
"""

from django.db import models
from django.utils import timezone
from .base import BaseModel
from .parties import Party
from .electorates import Electorate
from django.utils.text import slugify
from .gazette import GazetteNotice
from .documents import File
from django.core.validators import MinValueValidator
from .documents import Document
from colorfield.fields import ColorField


class Person(BaseModel):
    """
    A person entity. Plural: People.
    Current name fields stored here for fast queries.
    """
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True,blank=True,null=True)
    photo = models.ForeignKey(File, on_delete=models.SET_NULL, blank=True, null=True, related_name="people")
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)
    cached_description = models.TextField(blank=True, null=True)
    cached_colour = ColorField(blank=True, null=True)
    twitter_user = models.ForeignKey('TwitterUser', on_delete=models.SET_NULL, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.id or not self.slug:
            self.slug = slugify(self.display_name)
        super(Person, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "People"
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return self.display_name

    def change_name(self, first_name=None, last_name=None, display_name=None, effective_date=None):
        """
        Helper method to change name(s) and record history.
        Only provided fields will be updated.
        """
        if effective_date is None:
            effective_date = timezone.now().date()
        
        # Get current values before updating
        old_first_name = self.first_name
        old_last_name = self.last_name
        old_display_name = self.display_name
        
        # Check if any name is actually changing
        name_changed = (
            (first_name is not None and first_name != old_first_name) or
            (last_name is not None and last_name != old_last_name) or
            (display_name is not None and display_name != old_display_name)
        )
        
        if name_changed:
            # Record old name in history
            PersonNameHistory.objects.create(
                person=self,
                first_name=old_first_name,
                last_name=old_last_name,
                display_name=old_display_name,
                effective_until=effective_date
            )
            
            # Update current name fields
            if first_name is not None:
                self.first_name = first_name
            if last_name is not None:
                self.last_name = last_name
            if display_name is not None:
                self.display_name = display_name
            self.save()


class PersonNameHistory(BaseModel):
    """
    Historical record of person name changes.
    """
    person = models.ForeignKey(
        Person, 
        on_delete=models.CASCADE, 
        related_name='name_history',
        db_index=True
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200, blank=True)
    effective_from = models.DateField()  # When this name started
    effective_until = models.DateField()  # When it ended (when name changed)
    
    class Meta:
        verbose_name_plural = "Person Name History"
        ordering = ['-effective_until']  # Most recent changes first
        indexes = [
            models.Index(fields=['person', '-effective_until']),
        ]

    def __str__(self):
        name_str = self.display_name or f"{self.first_name} {self.last_name}"
        return f"{self.person} - {name_str} ({self.effective_from} to {self.effective_until})"


class ParliamentaryAffiliation(BaseModel):
    elected_date = models.DateField(blank=True, null=True)
    sworn_date = models.DateField(blank=True,null=True)
    end_date = models.DateField(blank=True,null=True)
    parliament = models.ForeignKey('Parliament',on_delete=models.CASCADE)
    person = models.ForeignKey('Person',on_delete=models.CASCADE)
    electorate = models.ForeignKey(Electorate,on_delete=models.CASCADE, blank=True, null=True)
    election = models.ForeignKey('Election', on_delete=models.SET_NULL, blank=True, null=True)
    fallback_electorate_slug = models.TextField(blank=True,null=True)
    replaced = models.ForeignKey('self',on_delete=models.SET_NULL, blank=True, null=True, related_name="replacements")
    gazette_notice_election = models.ForeignKey(GazetteNotice, on_delete=models.SET_NULL, blank=True, null=True, related_name="elected_affiliations")
    gazette_notice_vacation = models.ForeignKey(GazetteNotice, on_delete=models.SET_NULL, blank=True, null=True, related_name="vacated_affiliations")
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    END_REASONS = [
        ("e93_55_1_a", "Electoral Act 1993, s 55(1)(a): Non-attendance"),
        ("e93_55_1_b", "Electoral Act 1993, s 55(1)(b): Allegiance to foreign state"),
        ("e93_55_1_c", "Electoral Act 1993, s 55(1)(c): Subject or citizen of foreign state"),
        ("e93_55_1_ca", "Electoral Act 1993, s 55(1)(ca): Cessation of New Zealand citizenship"),
        ("e93_55_1_cb_i", "Electoral Act 1993, s 55(1)(cb)(i): Candidate in foreign Parliamentary election"),
        ("e93_55_1_cb_ii", "Electoral Act 1993, s 55(1)(cb)(ii): Candidate in foreign governing body election"),
        ("e93_55_1_d", "Electoral Act 1993, s 55(1)(d): Serious conviction or corruption"),
        ("e93_55_1_e", "Electoral Act 1993, s 55(1)(e): Became public servant"),
        ("e93_55_1_ea", "Electoral Act 1993, s 55(1)(ea): Appointed as electoral official"),
        ("e93_55_1_f", "Electoral Act 1993, s 55(1)(f): Resignation"),
        ("e93_55_1_f_by", "Electoral Act 1993, s 55(1)(f): Resignation (successful constituency candidate at by-election)"),
        ("e93_55_1_fa", "Electoral Act 1993, ss 55(1)(fa) and 55A: Cessation of party membership"),
        ("e93_55_1_g", "Electoral Act 1993, s 55(1)(g): Election voided on petition"),
        ("e93_55_1_h", "Electoral Act 1993, s 55(1)(h): Death"),
        ("e93_55_1_i", "Electoral Act 1993, s 55(1)(i): Mental disorder"),
        ("c86_18_2", "Constitution Act 1986, s 18(2): Dissolution of Parliamentary term"),
        ("c86_17", "Constitution Act 1986, s 17: Expiry of Parliamentary term"),
        ("e93_54", "Electoral Act 1993, s 54: Close of polling day at the next general election")
    ]

    START_REASONS = [
        ("e93_137", "Electoral Act 1993, s 137: Supply of list vacancy"),
        ("ge_elecorate", "Successful constituency candidate at general election"),
        ("ge_list", "Successful list candidate following general election"),
        ("by_electorate", "Successful constituency candidate at by-election"),
    ]

    END_REASONS_LOOKUP = dict(END_REASONS)
    START_REASONS_LOOKUP = dict(START_REASONS)
    end_reason = models.CharField(max_length=16, choices=END_REASONS, blank=True, null=True)
    start_reason = models.CharField(max_length=16, choices=START_REASONS, blank=True, null=True)

    def __str__(self):
        return f"{self.person.display_name} - {self.parliament.number} - {self.electorate.name if self.electorate else 'List'} - {self.start_reason if self.start_reason else ''} - {self.end_reason if self.end_reason else ''}"


class PartyAffiliation(BaseModel):
    person = models.ForeignKey(Person,on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField(blank=True,null=True)
    party = models.ForeignKey(Party,on_delete=models.CASCADE)
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    def __str__(self):
        return self.person.display_name + " " + self.party.display_name


class MinisterialPortfolio(BaseModel):
    name = models.TextField()
    slug = models.TextField(blank=True,null=True)
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.id or not self.slug:
            name = self.name.replace("ā","aa").replace("ē","ee").replace("ī","ii").replace("ō","oo").replace("ū","uu")
            self.slug = slugify(name)
            
        super(MinisterialPortfolio, self).save(*args, **kwargs)
    
    def __str__(self):
        return self.name

class MinisterialAffiliation(BaseModel):
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    title = models.TextField(blank=True, null=True)
    conjunction = models.TextField(blank=True, null=True)
    portfolio = models.ForeignKey(MinisterialPortfolio, on_delete=models.CASCADE)
    specialisation = models.TextField(blank=True, null=True)
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    APPOINTMENT_METHODS = [("l","Letter"), ("w","Warrant"),("pus w","Parliamentary Under-Secretary Warrant")]
    APPOINTMENT_METHODS_LOOKUP = dict(APPOINTMENT_METHODS)
    appointment_method = models.CharField(max_length=5, choices=APPOINTMENT_METHODS, blank=True, null=True)

    TYPES = [("p", "Portfolio"), ("r", "Responsibility")]
    TYPES_LOOKUP = dict(TYPES)
    type = models.CharField(max_length=1, choices=TYPES, default="p")

    @property
    def description(self):
        if self.title and self.conjunction and self.specialisation:
            return f"{self.title} {self.conjunction} {self.portfolio.name} ({self.specialisation})"
        elif self.title and self.conjunction:
            return f"{self.title} {self.conjunction} {self.portfolio.name}"
        elif self.title:
            return f"{self.title}, {self.portfolio.name}"
        else:
            return self.portfolio.name

    def __str__(self) -> str:
        return f"{self.person.display_name}, {self.description()}"

class FinancialInterestSnapshot(BaseModel):
    as_at = models.DateField()
    person = models.ForeignKey(Person,on_delete=models.CASCADE)
    document = models.ForeignKey(Document,on_delete=models.SET_NULL,blank=True,null=True)
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    def __str__(self):
        return f"{self.person.display_name} - {self.as_at}"

class FinancialInterest(BaseModel):
    TYPES = [("1","Company directorships and controlling interests"),("2", "Other companies and business entities"),("3", "Employment"),("4", "Beneficial interests in, and trusteeships of, trusts"),("5","Organisations and trusts seeking Government funding"),("6","Real property"),("7","Retirement schemes"),("8","Managed investment schemes"),("9","Debtors"),("10","Creditors"),("11","Overseas travel costs"),("12","Gifts"),("13","Discharged debts"),("14","Payments for activities")]
    interest_type = models.CharField(max_length=2,choices=TYPES)
    snapshot = models.ForeignKey(FinancialInterestSnapshot,on_delete=models.CASCADE)
    description = models.TextField()

    nzbn_entity_name = models.TextField(blank=True,null=True)
    nzbn = models.TextField(blank=True,null=True)
    nzbn_entity_type_code = models.TextField(blank=True,null=True)
    nzbn_entity_type_desc = models.TextField(blank=True, null=True)
    nzbn_entity_classifications = models.TextField(blank=True, null=True)
    nzbn_entity_classifications_descs = models.TextField(blank=True, null=True)


    def __str__(self):
        return f"{self.report} : {self.interestType} : {self.description}"