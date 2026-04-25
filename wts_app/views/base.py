from rest_framework.pagination import PageNumberPagination

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


class MPListPagination(PageNumberPagination):
    """Pagination for the members-of-parliament list (single page fits the full House)."""
    page_size = 200
    page_size_query_param = 'page_size'
    max_page_size = 1000