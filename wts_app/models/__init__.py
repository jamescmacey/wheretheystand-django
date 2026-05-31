"""
Models package for wts_app.

Import all models here so Django can discover them.
Models are organized into separate files by domain/functionality.
"""

# Import all models from their respective files
# This ensures Django's app registry can find them
from .base import *  # Base models, abstract models, mixins
from .people import *  # Person and PersonNameHistory
from .electorates import *  # Electorate
from .parties import *  # Party and PartyBrandHistory
from .parliaments import *  # Parliament
from .elections import *  # Election
from .banners import *  # Banner
from .bills import *  # Bill
from .votes import *  # Vote and VoteRecord
from .credit_card_expenses import *  # CreditCardReconciliation, CreditCardExpense
from .gemini import *  # Gemini batch processing
from .election_donation_returns import *  # ElectionDonationReturn
from .feedback import *  # Feedback
from .user import *  # User
from .workbooks import *  # Workbook, WorkbookFile
from .workbook_pipeline import *  # WorkbookStep
from .system_events import *  # MonitoredSource, SystemEvent
from .hansard import *  # HansardSearchResult, HansardDaily, HansardDebate, HansardItem, HansardBillAssocation

# Make all models available at the package level
__all__ = [
    'User',
]

