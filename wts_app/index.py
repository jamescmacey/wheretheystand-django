from algoliasearch_django import AlgoliaIndex
from algoliasearch_django.decorators import register

from .models import SiteSearch

@register(SiteSearch)
class SiteSearchIndex(AlgoliaIndex):
    settings = {
        "searchableAttributes": ["name", "description"],
        "attributesForFaceting": ["type"],
    }
    index_name = "SiteSearch"
    custom_objectID = "id_as_str"