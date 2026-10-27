"""Algolia indices.

One class per index. Registering a model here also connects post_save and
pre_delete receivers to it, so a single save reaches Algolia inline -- see
ALGOLIA["AUTO_INDEXING"] in settings for the switch that turns that off.
"""

from algoliasearch_django import AlgoliaIndex
from algoliasearch_django.decorators import register

from .models import SiteSearch
from .models.elections import ElectionVotingPlace

@register(SiteSearch)
class SiteSearchIndex(AlgoliaIndex):
    settings = {
        "searchableAttributes": ["name", "description"],
        "attributesForFaceting": ["type"],
    }
    index_name = "SiteSearch"
    custom_objectID = "id_as_str"


@register(ElectionVotingPlace)
class ElectionVotingPlaceIndex(AlgoliaIndex):
    """Voting places as they stood at one election, in their own index.

    Separate from SiteSearch rather than another `type` within it: these are
    searched on their own, by address and by proximity, and there are several
    thousand of them per election -- enough to drown site search if they shared
    an index with people, parties and bills.

    Only ElectionVotingPlace is indexed. A PersistentVotingPlace carries no
    election, electorate or number, so it cannot answer "where do I vote in this
    election"; it reaches the index only as the `persistent_voting_place`
    attribute, which groups the records for one physical place across elections.

    Every record carries its results version, so a query must filter on one.
    Without that filter a search returns the same address once per election it
    was used in.
    """

    index_name = "ElectionVotingPlaces"
    custom_objectID = "id_as_str"
    geo_field = "geoloc"

    fields = (
        ("id_as_str", "id"),
        "number",
        "address",
        ("electorate_name", "electorate_name"),
        ("electorate_number", "electorate_number"),
        ("results_version_id_as_str", "results_version"),
        ("results_version_name", "results_version_name"),
        ("election_id_as_str", "election"),
        ("election_name", "election_name"),
        ("event_id", "event"),
        ("persistent_voting_place_id_as_str", "persistent_voting_place"),
        "latitude",
        "longitude",
    )

    settings = {
        # Address first: the overwhelming majority of queries are a street, a
        # suburb or the name of a hall. The electorate is there so that typing
        # an electorate name narrows to its places, and the number so that
        # staff can jump straight to one off a results sheet.
        "searchableAttributes": [
            "address",
            "electorate_name",
            "unordered(number)",
        ],
        # results_version, election and event are filterOnly: they are UUIDs and
        # an event id, never shown in a facet list, so there is no reason to pay
        # for faceting on them.
        "attributesForFaceting": [
            "filterOnly(results_version)",
            "filterOnly(election)",
            "filterOnly(event)",
            "filterOnly(persistent_voting_place)",
            "electorate_name",
        ],
        "customRanking": ["asc(number)"],
        # Addresses are short and arrive with inconsistent abbreviations, so a
        # one-character typo on a short word would otherwise match nothing.
        "minWordSizefor1Typo": 3,
        "minWordSizefor2Typos": 7,
    }

    def get_queryset(self):
        """Every voting place, with the relations the record needs.

        Without this a full reindex of one election's places runs several
        thousand queries for the electorate, version and election names.
        """
        return ElectionVotingPlace.objects.select_related(
            "physical_electorate",
            "results_version",
            "results_version__election",
        ).order_by("number")
