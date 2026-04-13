"""
URL router for version 1 of the mibudge REST API.

Mounted at ``/api/v1/`` in the project URLconf. Cross-version endpoints
(JWT auth) live outside this router and stay at ``/api/token/...``.

Versioning policy: even though there is only one version today, all
resource endpoints live under ``/api/v1/`` so a future ``/api/v2/``
can be added without breaking clients that depend on the v1 contract.
The module path mirrors the URL -- each Django app owns an
``api/v1/`` subpackage for its v1 views, serializers, and filters.
"""

from django.conf import settings
from django.urls import path
from rest_framework.routers import DefaultRouter, SimpleRouter

from moneypools.api.v1.views import (
    BankAccountViewSet,
    BankViewSet,
    BudgetViewSet,
    InternalTransactionViewSet,
    TransactionAllocationViewSet,
    TransactionViewSet,
    currencies,
)
from users.api.v1.views import UserViewSet

if settings.DEBUG:
    router = DefaultRouter()
else:
    router = SimpleRouter()

router.register("users", UserViewSet)
router.register("banks", BankViewSet)
router.register("bank-accounts", BankAccountViewSet)
router.register("budgets", BudgetViewSet)
router.register("transactions", TransactionViewSet)
router.register("allocations", TransactionAllocationViewSet)
router.register("internal-transactions", InternalTransactionViewSet)


app_name = "api_v1"
urlpatterns = [
    path("currencies/", currencies, name="currencies"),
    *router.urls,
]
