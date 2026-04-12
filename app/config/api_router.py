from django.conf import settings
from django.urls import path
from rest_framework.routers import DefaultRouter, SimpleRouter

from moneypools.api.views import (
    BankAccountViewSet,
    BankViewSet,
    BudgetViewSet,
    InternalTransactionViewSet,
    TransactionAllocationViewSet,
    TransactionViewSet,
    currencies,
)
from users.api.views import UserViewSet

if settings.DEBUG:
    router = DefaultRouter()
else:
    router = SimpleRouter()

router.register("users", UserViewSet)
router.register("banks", BankViewSet)
router.register("accounts", BankAccountViewSet)
router.register("budgets", BudgetViewSet)
router.register("transactions", TransactionViewSet)
router.register("allocations", TransactionAllocationViewSet)
router.register("internal-transactions", InternalTransactionViewSet)


app_name = "api"
urlpatterns = [
    path("currencies/", currencies, name="currencies"),
    *router.urls,
]
