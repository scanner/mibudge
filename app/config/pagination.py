"""
Custom pagination classes for the mibudge API.

The default DRF PageNumberPagination does not allow clients to control
page size.  FlexiblePageNumberPagination exposes a ``page_size`` query
parameter so callers (particularly the importer scripts) can request
larger pages when pulling bulk data for deduplication, while keeping a
sensible default for UI pagination.
"""

# 3rd party imports
from rest_framework.pagination import PageNumberPagination


########################################################################
########################################################################
#
class FlexiblePageNumberPagination(PageNumberPagination):
    """Page-number pagination with client-controllable page size.

    Defaults to PAGE_SIZE from settings (100).  Clients may pass
    ``?page_size=N`` to request up to ``max_page_size`` items per page.
    """

    page_size_query_param = "page_size"
    max_page_size = 500
