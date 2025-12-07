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
    ElectorateListCreateView,
    ElectorateRetrieveUpdateDestroyView,
    ElectorateBoundarySetListCreateView,
    ElectorateBoundarySetRetrieveUpdateDestroyView,
    ElectorateBoundaryListCreateView,
    ElectorateBoundaryRetrieveUpdateDestroyView,
)

urlpatterns = [
    # Person endpoints
    path("people/", PersonListCreateView.as_view(), name="person-list-create"),
    path("people/<slug:slug>/", PersonRetrieveUpdateDestroyView.as_view(), name="person-detail"),

    # ParliamentaryAffiliation endpoints
    path("parliamentary-affiliations/", ParliamentaryAffiliationListCreateView.as_view(), name="parliamentaryaffiliation-list-create"),
    path("parliamentary-affiliations/<int:pk>/", ParliamentaryAffiliationRetrieveUpdateDestroyView.as_view(), name="parliamentaryaffiliation-detail"),

    # PartyAffiliation endpoints
    path("party-affiliations/", PartyAffiliationListCreateView.as_view(), name="partyaffiliation-list-create"),
    path("party-affiliations/<int:pk>/", PartyAffiliationRetrieveUpdateDestroyView.as_view(), name="partyaffiliation-detail"),

    # MinisterialAffiliation endpoints
    path("ministerial-affiliations/", MinisterialAffiliationListCreateView.as_view(), name="ministerialaffiliation-list-create"),
    path("ministerial-affiliations/<int:pk>/", MinisterialAffiliationRetrieveUpdateDestroyView.as_view(), name="ministerialaffiliation-detail"),

    # Category endpoints
    path("categories/", CategoryListCreateView.as_view(), name="category-list-create"),
    path("categories/<slug:slug>/", CategoryRetrieveUpdateDestroyView.as_view(), name="category-detail"),

    # CopyrightParty endpoints
    path("copyright-parties/", CopyrightPartyListCreateView.as_view(), name="copyrightparty-list-create"),
    path("copyright-parties/<int:pk>/", CopyrightPartyRetrieveUpdateDestroyView.as_view(), name="copyrightparty-detail"),

    # Licence endpoints
    path("licences/", LicenceListCreateView.as_view(), name="licence-list-create"),
    path("licences/<int:pk>/", LicenceRetrieveUpdateDestroyView.as_view(), name="licence-detail"),

    # Document endpoints
    path("documents/", DocumentListCreateView.as_view(), name="document-list-create"),
    path("documents/<slug:slug>/", DocumentRetrieveUpdateDestroyView.as_view(), name="document-detail"),

    # File endpoints
    path("files/", FileListCreateView.as_view(), name="file-list-create"),
    path("files/<int:pk>/", FileRetrieveUpdateDestroyView.as_view(), name="file-detail"),

    # DocumentCollection endpoints
    path("document-collections/", DocumentCollectionListCreateView.as_view(), name="documentcollection-list-create"),
    path("document-collections/<uuid:pk>/", DocumentCollectionRetrieveUpdateDestroyView.as_view(), name="documentcollection-detail"),

    # GazetteNotice endpoints
    path("gazette-notices/", GazetteNoticeListCreateView.as_view(), name="gazettenotice-list-create"),
    path("gazette-notices/<str:number>/", GazetteNoticeRetrieveUpdateDestroyView.as_view(), name="gazettenotice-detail"),

    # Electorate endpoints
    path("electorates/", ElectorateListCreateView.as_view(), name="electorate-list-create"),
    path("electorates/<slug:slug>/", ElectorateRetrieveUpdateDestroyView.as_view(), name="electorate-detail"),

    # ElectorateBoundarySet endpoints
    path("electorate-boundary-sets/", ElectorateBoundarySetListCreateView.as_view(), name="electorateboundaryset-list-create"),
    path("electorate-boundary-sets/<int:pk>/", ElectorateBoundarySetRetrieveUpdateDestroyView.as_view(), name="electorateboundaryset-detail"),

    # ElectorateBoundary endpoints
    path("electorate-boundaries/", ElectorateBoundaryListCreateView.as_view(), name="electorateboundary-list-create"),
    path("electorate-boundaries/<int:pk>/", ElectorateBoundaryRetrieveUpdateDestroyView.as_view(), name="electorateboundary-detail"),
]
