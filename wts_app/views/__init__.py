"""
Views package for wts_app.

Import all views here so they can be easily imported elsewhere.
Views are organized into separate files by domain/functionality.
"""

# Import all views from their respective files
from .people import *  # Person, ParliamentaryAffiliation, PartyAffiliation, MinisterialAffiliation views
from .electorates import *  # Electorate views
from .parties import *  # Party views
from .parliaments import *  # Parliament views
from .elections import *  # Election views
from .documents import *  # Category, CopyrightParty, Licence, Document, File, DocumentCollection views
from .gazette import *  # GazetteNotice views

# Make all views available at the package level
__all__ = [
    # Add view names here as you create them
]

