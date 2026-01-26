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
from .x import *  # XUser and XMetrics

# from .analytics import *  # Analytics/tracking models
# from .relationships import *  # Many-to-many, foreign key relationships

# Make all models available at the package level
__all__ = [
    # Add model names here as you create them
    # Example: 'User', 'Post', 'Comment', etc.
]

