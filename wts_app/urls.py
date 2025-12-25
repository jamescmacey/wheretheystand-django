from django.urls import path
from .views import (
    PersonListCreateView,
    PersonRetrieveUpdateDestroyView,
    ParliamentaryAffiliationListCreateView,
    ParliamentaryAffiliationRetrieveUpdateDestroyView,
    PartyAffiliationListCreateView,
    PartyAffiliationRetrieveUpdateDestroyView,
    MinisterialAffiliationListCreateView,
    MinisterialAffiliationRetrieveUpdateDestroyView,
    CategoryListCreateView,
    CategoryRetrieveUpdateDestroyView,
    CopyrightPartyListCreateView,
    CopyrightPartyRetrieveUpdateDestroyView,
    LicenceListCreateView,
    LicenceRetrieveUpdateDestroyView,
    DocumentListCreateView,
    DocumentRetrieveUpdateDestroyView,
    FileListCreateView,
    FileRetrieveUpdateDestroyView,
    DocumentCollectionListCreateView,
    DocumentCollectionRetrieveUpdateDestroyView,
    GazetteNoticeListCreateView,
    GazetteNoticeRetrieveUpdateDestroyView,
    ElectionListCreateView,
    ElectionRetrieveUpdateDestroyView,
    ElectorateListCreateView,
    ElectorateRetrieveUpdateDestroyView,
    ElectorateBoundarySetListCreateView,
    ElectorateBoundarySetRetrieveUpdateDestroyView,
    ElectorateBoundaryListCreateView,
    ElectorateBoundaryRetrieveUpdateDestroyView,
    PersonFinancialInterestsView,
    PersonFinancialInterestLatestView,
    PersonFinancialInterestSnapshotListCreateView,
    PersonFinancialInterestSnapshotRetrieveUpdateDestroyView,
    MPListView,
    BannerListCreateView,
    BannerRetrieveUpdateDestroyView,
    BillListCreateView,
    BillRetrieveUpdateDestroyView,
    VoteListCreateView,
    VoteRetrieveUpdateDestroyView,
    VoteRecordListCreateView,
    VoteRecordRetrieveUpdateDestroyView,
    PersistentDataDownloadView,
    ResultsVersionReferenceDataView,
    ResultsVersionResultsView,
    ResultsVersionResultsByElectorateView,
    ResultsVersionResultsByVotingPlaceView,
    PersonElectionResultsView
)

urlpatterns = [
    # Person endpoints
    path("people/", PersonListCreateView.as_view(), name="person-list-create"),
    path("people/<slug:slug>/", PersonRetrieveUpdateDestroyView.as_view(), name="person-detail"),
    path("people/<slug:slug>/election-results/", PersonElectionResultsView.as_view(), name="person-election-results"),
    path("people/<slug:slug>/financial-interests/", PersonFinancialInterestsView.as_view(), name="person-financial-interests"),
    path("people/<slug:slug>/financial-interests/latest/", PersonFinancialInterestLatestView.as_view(), name="person-financial-interests-latest"),
    path("people/<slug:slug>/financial-interests/<uuid:pk>/", PersonFinancialInterestSnapshotRetrieveUpdateDestroyView.as_view(), name="person-financial-snapshot-detail"),

    # ParliamentaryAffiliation endpoints
    path("parliamentary-affiliations/", ParliamentaryAffiliationListCreateView.as_view(), name="parliamentaryaffiliation-list-create"),
    path("parliamentary-affiliations/<uuid:pk>/", ParliamentaryAffiliationRetrieveUpdateDestroyView.as_view(), name="parliamentaryaffiliation-detail"),

    # PartyAffiliation endpoints
    path("party-affiliations/", PartyAffiliationListCreateView.as_view(), name="partyaffiliation-list-create"),
    path("party-affiliations/<uuid:pk>/", PartyAffiliationRetrieveUpdateDestroyView.as_view(), name="partyaffiliation-detail"),

    # MinisterialAffiliation endpoints
    path("ministerial-affiliations/", MinisterialAffiliationListCreateView.as_view(), name="ministerialaffiliation-list-create"),
    path("ministerial-affiliations/<uuid:pk>/", MinisterialAffiliationRetrieveUpdateDestroyView.as_view(), name="ministerialaffiliation-detail"),

    # Category endpoints
    path("categories/", CategoryListCreateView.as_view(), name="category-list-create"),
    path("categories/<slug:slug>/", CategoryRetrieveUpdateDestroyView.as_view(), name="category-detail"),

    # CopyrightParty endpoints
    path("copyright-parties/", CopyrightPartyListCreateView.as_view(), name="copyrightparty-list-create"),
    path("copyright-parties/<uuid:pk>/", CopyrightPartyRetrieveUpdateDestroyView.as_view(), name="copyrightparty-detail"),

    # Licence endpoints
    path("licences/", LicenceListCreateView.as_view(), name="licence-list-create"),
    path("licences/<uuid:pk>/", LicenceRetrieveUpdateDestroyView.as_view(), name="licence-detail"),

    # Document endpoints
    path("documents/", DocumentListCreateView.as_view(), name="document-list-create"),
    path("documents/<slug:slug>/", DocumentRetrieveUpdateDestroyView.as_view(), name="document-detail"),

    # File endpoints
    path("files/", FileListCreateView.as_view(), name="file-list-create"),
    path("files/<uuid:pk>/", FileRetrieveUpdateDestroyView.as_view(), name="file-detail"),

    # DocumentCollection endpoints
    path("document-collections/", DocumentCollectionListCreateView.as_view(), name="documentcollection-list-create"),
    path("document-collections/<uuid:pk>/", DocumentCollectionRetrieveUpdateDestroyView.as_view(), name="documentcollection-detail"),

    # GazetteNotice endpoints
    path("gazette-notices/", GazetteNoticeListCreateView.as_view(), name="gazettenotice-list-create"),
    path("gazette-notices/<str:number>/", GazetteNoticeRetrieveUpdateDestroyView.as_view(), name="gazettenotice-detail"),

    # Election endpoints (using election_results views for ID-only serialization)
    path("elections/", ElectionListCreateView.as_view(), name="election-list-create"),
    path("elections/persistent-data/", PersistentDataDownloadView.as_view(), name="persistent-data-download"),
    path("elections/<str:slug>/", ElectionRetrieveUpdateDestroyView.as_view(), name="election-detail"),
    
    path("elections/<str:slug>/<str:version_slug>/reference-data/", ResultsVersionReferenceDataView.as_view(), name="results-version-reference-data"),
    path("elections/<str:slug>/<str:version_slug>/results/", ResultsVersionResultsView.as_view(), name="results-version-results"),
    path("elections/<str:slug>/<str:version_slug>/results/by-electorate/<str:electorate_id>/", ResultsVersionResultsByElectorateView.as_view(), name="results-version-results-by-electorate"),
    path("elections/<str:slug>/<str:version_slug>/results/by-voting-place/<str:voting_place_id>/", ResultsVersionResultsByVotingPlaceView.as_view(), name="results-version-results-by-voting-place"),

    # Electorate endpoints
    path("electorates/", ElectorateListCreateView.as_view(), name="electorate-list-create"),
    path("electorates/<slug:slug>/", ElectorateRetrieveUpdateDestroyView.as_view(), name="electorate-detail"),

    # ElectorateBoundarySet endpoints
    path("electorate-boundary-sets/", ElectorateBoundarySetListCreateView.as_view(), name="electorateboundaryset-list-create"),
    path("electorate-boundary-sets/<uuid:pk>/", ElectorateBoundarySetRetrieveUpdateDestroyView.as_view(), name="electorateboundaryset-detail"),

    # ElectorateBoundary endpoints
    path("electorate-boundaries/", ElectorateBoundaryListCreateView.as_view(), name="electorateboundary-list-create"),
    path("electorate-boundaries/<uuid:pk>/", ElectorateBoundaryRetrieveUpdateDestroyView.as_view(), name="electorateboundary-detail"),

    # Members of Parliament endpoints
    path("members-of-parliament/", MPListView.as_view(), name="members-of-parliament"),

    # Banner endpoints
    path("banners/", BannerListCreateView.as_view(), name="banner-list-create"),
    path("banners/<uuid:pk>/", BannerRetrieveUpdateDestroyView.as_view(), name="banner-detail"),

    # Bill endpoints
    path("bills/", BillListCreateView.as_view(), name="bill-list-create"),
    path("bills/<uuid:pk>/", BillRetrieveUpdateDestroyView.as_view(), name="bill-detail"),

    # Vote endpoints
    path("votes/", VoteListCreateView.as_view(), name="vote-list-create"),
    path("votes/<uuid:pk>/", VoteRetrieveUpdateDestroyView.as_view(), name="vote-detail"),

    # VoteRecord endpoints
    path("vote-records/", VoteRecordListCreateView.as_view(), name="voterecord-list-create"),
    path("vote-records/<uuid:pk>/", VoteRecordRetrieveUpdateDestroyView.as_view(), name="voterecord-detail"),
]
