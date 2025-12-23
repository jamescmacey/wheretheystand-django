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
from .financial_interests import *  # Financial interest views
from .members_of_parliament import *  # Members of Parliament views
from .banners import *  # Banner views
from .bills import *  # Bill views
from .votes import *  # Vote views
from .election_results import *  # Election results views
