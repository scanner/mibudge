"""Tests for the moneypools REST API: serializers, views, and permissions."""

# system imports
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

# 3rd party imports
import pytest
import pytest_check as check
import recurrence
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from djmoney.money import Money
from rest_framework import status
from rest_framework.test import APIClient

# Project imports
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    EventKind,
    FundingEventOccurrence,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
    TransactionCategory,
    get_default_currency,
)
from moneypools.service import transaction as transaction_svc
from tests.moneypools.factories import (
    BankAccountFactory,
    BudgetFactory,
    TransactionFactory,
)
from users.models import User

# Monthly schedule anchored Jan 1 -- dtstart controls which day-of-month fires.
_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)

# Weekly schedule anchored on a Friday.
_WEEKLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 9),
    rrules=[recurrence.Rule(recurrence.WEEKLY)],
)

pytestmark = pytest.mark.django_db


####################################################################
#
def _splits_url(tx: Transaction) -> str:
    """The splits action URL for `tx`."""
    return reverse("api_v1:transaction-splits", kwargs={"id": tx.id})


####################################################################
#
@pytest.fixture
def make_scheduled_budget(
    account: BankAccount, make_budget: Callable[..., Budget]
) -> Callable[..., Budget]:
    """Return a factory for scheduled budgets on `account`.

    A thin layer over `make_budget` with defaults for these tests.

    Returns:
        A callable `(last_funded_on=None, last_recurrence_on=None,
        **overrides) -> Budget`.  By default the budget is a $1000
        fixed-amount Goal funded $100 monthly (the $100 applies only to
        fixed-amount budgets).  `overrides` pass through
        to `make_budget`; the two dates, when given, are written
        after creation to place the funding and recurrence pointers.
    """

    def _make(
        last_funded_on: date | None = None,
        last_recurrence_on: date | None = None,
        **overrides: Any,
    ) -> Budget:
        kwargs: dict[str, Any] = {
            "budget_type": Budget.BudgetType.GOAL,
            "funding_type": Budget.FundingType.FIXED_AMOUNT,
            "target_balance": Money(1000, "USD"),
            "funding_schedule": _MONTHLY,
        }
        kwargs.update(overrides)
        if kwargs["funding_type"] == Budget.FundingType.FIXED_AMOUNT:
            kwargs.setdefault("funding_amount", Money(100, "USD"))
        pointers = {
            name: value
            for name, value in (
                ("last_funded_on", last_funded_on),
                ("last_recurrence_on", last_recurrence_on),
            )
            if value is not None
        }
        return make_budget(account, stored=pointers, **kwargs)

    return _make


####################################################################
#
@pytest.fixture
def spent_tx(
    account: BankAccount, transaction_factory: Callable[..., Transaction]
) -> Transaction:
    """A posted -$100 transaction on `account`, allocated to Unallocated."""
    return transaction_factory(
        bank_account=account, amount=Money(-100, "USD"), pending=False
    )


########################################################################
########################################################################
#
class TestAuthRequired:
    """Read endpoints reject unauthenticated clients."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url_name",
        [
            "api_v1:currencies",
            "api_v1:bank-list",
            "api_v1:transactionallocation-list",
            "api_v1:transaction-category-list",
        ],
    )
    def test_list_requires_auth(
        self, api_client: APIClient, url_name: str
    ) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  it GETs a list endpoint
        THEN:  401 Unauthorized is returned
        """
        response = api_client.get(reverse(url_name))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


########################################################################
########################################################################
#
class TestCurrenciesAPI:
    """Tests for the /api/v1/currencies/ endpoint."""

    ####################################################################
    #
    def test_list_currencies(self, auth_client: APIClient) -> None:
        """
        GIVEN: an authenticated client
        WHEN:  GET /api/v1/currencies/
        THEN:  a list of currency objects is returned, each with code,
               name, and numeric fields, sorted by code
        """
        response = auth_client.get(reverse("api_v1:currencies"))

        assert response.status_code == status.HTTP_200_OK
        usd = next(c for c in response.data if c["code"] == "USD")
        check.equal(usd["name"], "US Dollar", "USD has its name")
        check.equal(usd["numeric"], "840", "and its numeric code")
        codes = [c["code"] for c in response.data]
        check.equal(codes, sorted(codes), "sorted by code")


########################################################################
########################################################################
#
class TestBankAPI:
    """Tests for the read-only /api/v1/banks/ endpoint."""

    ####################################################################
    #
    def test_list_banks(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: two banks exist
        WHEN:  GET /api/v1/banks/
        THEN:  both banks are returned with expected fields
        """
        bank_factory()
        bank_factory()

        response = auth_client.get(reverse("api_v1:bank-list"))

        assert response.status_code == status.HTTP_200_OK
        check.equal(response.data["count"], 2, "both banks")
        check.is_true(
            {"id", "name", "default_currency"}
            <= set(response.data["results"][0]),
            "with the expected fields",
        )

    ####################################################################
    #
    def test_list_page_out_of_range(self, auth_client: APIClient) -> None:
        """
        GIVEN: no banks beyond the first page
        WHEN:  GET /api/v1/banks/?page=999
        THEN:  404, a status the schema documents for the list
        """
        response = auth_client.get(reverse("api_v1:bank-list"), {"page": 999})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    ####################################################################
    #
    def test_retrieve_bank(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists
        WHEN:  GET /api/v1/banks/<uuid>/
        THEN:  the bank detail is returned
        """
        bank = bank_factory()

        response = auth_client.get(
            reverse("api_v1:bank-detail", kwargs={"id": bank.id})
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == bank.name

    ####################################################################
    #
    def test_create_not_allowed(self, auth_client: APIClient) -> None:
        """
        GIVEN: an authenticated client
        WHEN:  POST /api/v1/banks/
        THEN:  405 Method Not Allowed is returned
        """
        response = auth_client.post(
            reverse("api_v1:bank-list"), {"name": "New Bank"}
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


########################################################################
########################################################################
#
class TestBankAccountAPI:
    """Tests for the /api/v1/bank-accounts/ endpoint."""

    ####################################################################
    #
    def test_create_account(
        self,
        auth_client: APIClient,
        user: User,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists and an authenticated user
        WHEN:  POST /api/v1/bank-accounts/ with name, bank, and account_type
        THEN:  the account is created and the user is added as owner
        """
        bank = bank_factory()

        response = auth_client.post(
            reverse("api_v1:bankaccount-list"),
            {"name": "My Checking", "bank": str(bank.id), "account_type": "C"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        check.equal(response.data["name"], "My Checking", "named")
        check.is_not_none(
            response.data["unallocated_budget"], "with an unallocated budget"
        )
        account = BankAccount.objects.get(id=response.data["id"])
        check.is_true(
            account.owners.filter(pk=user.pk).exists(), "owned by the user"
        )

    ####################################################################
    #
    def test_create_account_with_initial_balance(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists
        WHEN:  POST /api/v1/bank-accounts/ with available_balance set
        THEN:  the account is created with the specified balance and
               the unallocated budget receives that balance
        """
        bank = bank_factory()

        response = auth_client.post(
            reverse("api_v1:bankaccount-list"),
            {
                "name": "Savings",
                "bank": str(bank.id),
                "account_type": "S",
                "available_balance": "1500.00",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        account = BankAccount.objects.get(id=response.data["id"])
        check.equal(
            account.available_balance.amount,
            Decimal("1500.00"),
            "account has the balance",
        )
        unalloc = account.unallocated_budget
        assert unalloc is not None
        check.equal(
            unalloc.balance.amount,
            Decimal("1500.00"),
            "and so does its unallocated budget",
        )

    ####################################################################
    #
    def test_create_account_with_currency(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists
        WHEN:  POST /api/v1/bank-accounts/ with currency=EUR
        THEN:  the account and its balances use EUR
        """
        bank = bank_factory()

        response = auth_client.post(
            reverse("api_v1:bankaccount-list"),
            {
                "name": "Euro Account",
                "bank": str(bank.id),
                "account_type": "C",
                "currency": "EUR",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        account = BankAccount.objects.get(id=response.data["id"])
        check.equal(account.currency, "EUR", "account currency")
        check.equal(
            str(account.posted_balance_currency),  # type: ignore[attr-defined]
            "EUR",
            "balance currency",
        )

    ####################################################################
    #
    def test_currency_immutable_after_create(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an existing bank account
        WHEN:  PATCH /api/v1/bank-accounts/<uuid>/ with a different currency
        THEN:  400 Bad Request with a currency validation error
        """
        response = auth_client.patch(
            reverse("api_v1:bankaccount-detail", kwargs={"id": account.id}),
            {"currency": "GBP"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "currency" in response.data

    ####################################################################
    #
    def test_list_only_owned_accounts(
        self,
        auth_client: APIClient,
        account: BankAccount,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: two accounts exist -- one owned by the user, one by another
        WHEN:  GET /api/v1/bank-accounts/
        THEN:  only the owned account is returned
        """
        bank_account_factory()  # owned by a different user

        response = auth_client.get(reverse("api_v1:bankaccount-list"))

        assert response.status_code == status.HTTP_200_OK
        assert [a["id"] for a in response.data["results"]] == [str(account.id)]

    ####################################################################
    #
    def test_update_name(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an existing bank account
        WHEN:  PATCH /api/v1/bank-accounts/<uuid>/ with a new name
        THEN:  the name is updated
        """
        response = auth_client.patch(
            reverse("api_v1:bankaccount-detail", kwargs={"id": account.id}),
            {"name": "Renamed Account"},
        )

        assert response.status_code == status.HTTP_200_OK
        account.refresh_from_db()
        assert account.name == "Renamed Account"


########################################################################
########################################################################
#
class TestBankAccountFundingSummaryAPI:
    """Tests for GET /api/v1/bank-accounts/<id>/funding-summary/."""

    ####################################################################
    #
    def _url(self, account: BankAccount) -> str:
        return f"/api/v1/bank-accounts/{account.id}/funding-summary/"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "specs,expected_group_count,expected_total",
        [
            # No schedulable budgets -- only the auto-created unallocated
            # budget exists, which has no funding schedule.
            ([], 0, Decimal("0")),
            # Two active budgets on the same schedule are grouped.
            (
                [(100, "monthly", False), (75, "monthly", False)],
                1,
                Decimal("175"),
            ),
            # Two different schedules produce two entries.
            (
                [(500, "monthly", False), (50, "weekly", False)],
                2,
                Decimal("550"),
            ),
            # Paused budget is excluded; only the active one counts.
            (
                [(100, "monthly", False), (200, "monthly", True)],
                1,
                Decimal("100"),
            ),
        ],
    )
    def test_grouping_totals_and_exclusions(
        self,
        specs: list[tuple[int, str, bool]],
        expected_group_count: int,
        expected_total: Decimal,
        auth_client: APIClient,
        account: BankAccount,
        make_scheduled_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a set of budgets, each (funding amount, schedule, paused)
        WHEN:  GET funding-summary
        THEN:  schedules are grouped by RRULE, paused budgets excluded,
               and grand total matches the sum of active funding amounts
        """
        schedules = {"monthly": _MONTHLY, "weekly": _WEEKLY}
        for amount, schedule, paused in specs:
            make_scheduled_budget(
                last_funded_on=date(2026, 4, 1),
                funding_amount=Money(amount, "USD"),
                funding_schedule=schedules[schedule],
                paused=paused,
            )

        response = auth_client.get(self._url(account))

        assert response.status_code == status.HTTP_200_OK
        check.equal(
            len(response.data["schedules"]), expected_group_count, "groups"
        )
        check.equal(
            Decimal(response.data["total_amount"]), expected_total, "total"
        )

    ####################################################################
    #
    def test_schedule_entry_fields(
        self,
        auth_client: APIClient,
        account: BankAccount,
        make_scheduled_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: one budget funded $100 on a monthly schedule
        WHEN:  GET funding-summary
        THEN:  each schedule entry contains schedule, next_date (ISO date),
               total_amount, currency, and budget_count
        """
        make_scheduled_budget(last_funded_on=date(2026, 4, 1))

        response = auth_client.get(self._url(account))

        assert response.status_code == status.HTTP_200_OK
        entry = response.data["schedules"][0]
        check.is_in("schedule", entry, "has the schedule")
        check.equal(
            Decimal(entry["total_amount"]), Decimal("100.00"), "total amount"
        )
        check.equal(entry["currency"], "USD", "currency")
        check.equal(entry["budget_count"], 1, "budget count")
        check.greater(
            date.fromisoformat(entry["next_date"]),
            date(2026, 4, 1),
            "next_date is an ISO date after the last funding",
        )

    ####################################################################
    #
    def test_non_owner_gets_404(
        self,
        account: BankAccount,
        user_factory: Callable[..., User],
        make_auth_client: Callable[[User], APIClient],
    ) -> None:
        """
        GIVEN: an account owned by user A
        WHEN:  user B (authenticated) requests funding-summary
        THEN:  404 -- the account is not in user B's queryset
        """
        response = make_auth_client(user_factory()).get(self._url(account))
        assert response.status_code == status.HTTP_404_NOT_FOUND


########################################################################
########################################################################
#
class TestBudgetNextFundingField:
    """API-level tests for the next_funding SerializerMethodField on Budget.

    Service-level logic (what next_funding_info returns for each budget
    type) is covered in test_funding.py.  These tests verify the field
    appears in the API response with the expected shape and nullability.
    """

    ####################################################################
    #
    def test_populated_for_active_budget(
        self,
        auth_client: APIClient,
        make_scheduled_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an active budget funded $100 monthly
        WHEN:  GET /api/v1/budgets/<id>/
        THEN:  next_funding holds the next date, amount and currency
        """
        budget = make_scheduled_budget(last_funded_on=date(2026, 4, 1))

        response = auth_client.get(f"/api/v1/budgets/{budget.id}/")

        assert response.status_code == status.HTTP_200_OK
        nf = response.data["next_funding"]
        assert nf is not None
        check.greater(
            date.fromisoformat(nf["date"]), date(2026, 4, 1), "next date"
        )
        check.equal(Decimal(nf["amount"]), Decimal("100.00"), "amount")
        check.equal(nf["amount_currency"], "USD", "currency")

    ####################################################################
    #
    def test_null_for_paused_budget(
        self,
        auth_client: APIClient,
        make_scheduled_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a paused budget with a funding schedule
        WHEN:  GET /api/v1/budgets/<id>/
        THEN:  next_funding is null
        """
        budget = make_scheduled_budget(
            last_funded_on=date(2026, 4, 1), paused=True
        )

        response = auth_client.get(f"/api/v1/budgets/{budget.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["next_funding"] is None


########################################################################
########################################################################
#
class TestBudgetNextRecurrenceField:
    """API-level tests for the next_recurrence SerializerMethodField.

    Service-level logic (which date next_recurrence_date returns) is
    covered in test_funding.py.  These tests verify the field appears
    in the API response with the expected shape and nullability.
    """

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_type,expected",
        [
            # Recurring: first occurrence after last_recurrence_on,
            # not the schedule's DTSTART (Jan 1).
            (Budget.BudgetType.RECURRING, "2026-08-01"),
            # Non-recurring budgets have no recurrence -> null.
            (Budget.BudgetType.GOAL, None),
        ],
    )
    def test_next_recurrence_field_in_budget_response(
        self,
        budget_type: str,
        expected: str | None,
        auth_client: APIClient,
        make_scheduled_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a RECURRING budget refreshed on Jul 1, or a GOAL budget
        WHEN:  GET /api/v1/budgets/<id>/
        THEN:  next_recurrence is the upcoming refresh date, or null
        """
        budget = make_scheduled_budget(
            last_recurrence_on=date(2026, 7, 1),
            budget_type=budget_type,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(500, "USD"),
            recurrence_schedule=_MONTHLY,
        )

        response = auth_client.get(f"/api/v1/budgets/{budget.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["next_recurrence"] == expected


########################################################################
########################################################################
#
class TestRecurrenceScheduleValidation:
    """recurrence_schedule accepts only the restricted refresh grammar.

    The refresh cycle is a single RRULE (WEEKLY/MONTHLY/YEARLY plus an
    optional INTERVAL) anchored by an optional DTSTART.  Richer RFC 2445
    shapes are rejected because BY* parts silently override the DTSTART
    anchor and the funding engine assumes one boundary per cycle.  The
    funding_schedule field is intentionally NOT restricted this way.
    """

    ####################################################################
    #
    @pytest.fixture
    def post_budget(
        self, auth_client: APIClient, account: BankAccount
    ) -> Callable[..., Any]:
        """Return a function POSTing a recurring budget with given schedules."""

        def _post(**schedules: str) -> Any:
            return auth_client.post(
                reverse("api_v1:budget-list"),
                {
                    "name": "Mortgage",
                    "bank_account": str(account.id),
                    "budget_type": "R",
                    "funding_type": "D",
                    "target_balance": "2088.00",
                    **schedules,
                },
            )

        return _post

    ####################################################################
    #
    @pytest.mark.parametrize(
        "rule",
        [
            # One per supported cycle, with and without the optional
            # INTERVAL and DTSTART anchor.
            pytest.param("RRULE:FREQ=MONTHLY", id="monthly"),
            pytest.param("RRULE:FREQ=WEEKLY;INTERVAL=2", id="biweekly"),
            pytest.param(
                "DTSTART:20260615T000000Z\nRRULE:FREQ=YEARLY;INTERVAL=2",
                id="biyearly_anchored",
            ),
        ],
    )
    def test_supported_cycle_accepted(
        self, post_budget: Callable[..., Any], rule: str
    ) -> None:
        """
        GIVEN: a budget create payload whose recurrence_schedule is a
               simple weekly, monthly or yearly cycle
        WHEN:  POST /api/v1/budgets/
        THEN:  201 Created
        """
        response = post_budget(recurrence_schedule=rule)
        assert response.status_code == status.HTTP_201_CREATED

    ####################################################################
    #
    @pytest.mark.parametrize(
        "rule",
        [
            # Day parts must come from DTSTART, not BY*.
            pytest.param(
                "DTSTART:20260708T000000Z\nRRULE:FREQ=MONTHLY;BYMONTHDAY=1",
                id="bymonthday",
            ),
            pytest.param(
                "RRULE:FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1", id="last_friday"
            ),
            pytest.param(
                "RRULE:FREQ=YEARLY;BYMONTH=4,12;BYMONTHDAY=10",
                id="multi_month_yearly",
            ),
            # A refresh cycle does not end (COUNT or UNTIL).
            pytest.param("RRULE:FREQ=MONTHLY;COUNT=12", id="count"),
            pytest.param(
                "RRULE:FREQ=MONTHLY;UNTIL=20270101T000000Z", id="until"
            ),
            # Unsupported frequency and rule sets.
            pytest.param("RRULE:FREQ=DAILY", id="daily"),
            pytest.param(
                "RRULE:FREQ=MONTHLY\nRRULE:FREQ=WEEKLY", id="multiple_rrules"
            ),
            pytest.param(
                "RRULE:FREQ=MONTHLY\nEXDATE:20261201T000000Z", id="exdate"
            ),
        ],
    )
    def test_richer_rule_rejected(
        self, post_budget: Callable[..., Any], rule: str
    ) -> None:
        """
        GIVEN: a budget create payload whose recurrence_schedule uses a
               richer RFC 2445 shape than a simple cycle
        WHEN:  POST /api/v1/budgets/
        THEN:  400 with a recurrence_schedule error
        """
        response = post_budget(recurrence_schedule=rule)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "recurrence_schedule" in response.data

    ####################################################################
    #
    def test_funding_schedule_keeps_full_grammar(
        self, post_budget: Callable[..., Any]
    ) -> None:
        """
        GIVEN: a budget create payload with a BYMONTHDAY funding_schedule
        WHEN:  POST /api/v1/budgets/
        THEN:  it is accepted -- only recurrence_schedule is restricted.
        """
        response = post_budget(
            funding_schedule="RRULE:FREQ=MONTHLY;BYMONTHDAY=15,-1",
            recurrence_schedule="DTSTART:20260708T000000Z\nRRULE:FREQ=MONTHLY",
        )
        assert response.status_code == status.HTTP_201_CREATED


########################################################################
########################################################################
#
class TestBudgetAPI:
    """Tests for the /api/v1/budgets/ endpoint."""

    ####################################################################
    #
    def test_create_budget(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an owned bank account
        WHEN:  POST /api/v1/budgets/ with required fields
        THEN:  a new budget is created under that account
        """
        response = auth_client.post(
            reverse("api_v1:budget-list"),
            {
                "name": "Groceries",
                "bank_account": str(account.id),
                "budget_type": "R",
                "funding_type": "D",
                "target_balance": "500.00",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        check.equal(response.data["name"], "Groceries", "named")
        check.equal(
            str(response.data["bank_account"]), str(account.id), "on account"
        )

    ####################################################################
    #
    def test_list_budgets_filtered_by_account(
        self,
        auth_client: APIClient,
        user: User,
        account: BankAccount,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: budgets on two different owned accounts
        WHEN:  GET /api/v1/budgets/?bank_account=<uuid>
        THEN:  only budgets for the specified account are returned
        """
        other_account = bank_account_factory(owners=[user])
        budget_factory(bank_account=account)
        budget_factory(bank_account=other_account)

        response = auth_client.get(
            reverse("api_v1:budget-list"), {"bank_account": str(account.id)}
        )

        assert response.status_code == status.HTTP_200_OK
        # The auto-created unallocated budget plus the one we made.
        assert {str(b["bank_account"]) for b in response.data["results"]} == {
            str(account.id)
        }

    ####################################################################
    #
    def test_cannot_delete_unallocated_budget(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an account's unallocated budget
        WHEN:  DELETE /api/v1/budgets/<uuid>/
        THEN:  403 Forbidden is returned
        """
        unalloc = account.unallocated_budget
        assert unalloc is not None

        response = auth_client.delete(
            reverse("api_v1:budget-detail", kwargs={"id": unalloc.id})
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    ####################################################################
    #
    def test_cannot_rename_unallocated_budget(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an account's unallocated budget
        WHEN:  PATCH /api/v1/budgets/<uuid>/ with a new name
        THEN:  400 Bad Request with a name validation error
        """
        unalloc = account.unallocated_budget
        assert unalloc is not None

        response = auth_client.patch(
            reverse("api_v1:budget-detail", kwargs={"id": unalloc.id}),
            {"name": "Sneaky Rename"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "name" in response.data

    ####################################################################
    #
    def test_budget_type_immutable(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an existing budget with type Goal
        WHEN:  PATCH with budget_type=R
        THEN:  400 Bad Request is returned
        """
        budget = budget_factory(bank_account=account, budget_type="G")

        response = auth_client.patch(
            reverse("api_v1:budget-detail", kwargs={"id": budget.id}),
            {"budget_type": "R"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "budget_type" in response.data

    ####################################################################
    #
    def test_delete_blocked_when_budget_has_allocations(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a budget with at least one transaction allocation
        WHEN:  DELETE /api/v1/budgets/<uuid>/
        THEN:  400 Bad Request is returned and the budget still exists
        """
        budget = budget_factory(bank_account=account)
        txn = transaction_factory(bank_account=account, amount=-50)
        transaction_allocation_factory(
            transaction=txn, budget=budget, amount=-50
        )

        response = auth_client.delete(
            reverse("api_v1:budget-detail", kwargs={"id": budget.id})
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Budget.objects.filter(id=budget.id).exists()

    ####################################################################
    #
    def test_delete_allowed_when_budget_has_no_allocations(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget with no transaction allocations
        WHEN:  DELETE /api/v1/budgets/<uuid>/
        THEN:  204 No Content is returned and the budget no longer exists
        """
        budget = budget_factory(bank_account=account)

        response = auth_client.delete(
            reverse("api_v1:budget-detail", kwargs={"id": budget.id})
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Budget.objects.filter(id=budget.id).exists()

    ####################################################################
    #
    def test_archive_moves_balance_to_unallocated(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget with a non-zero balance
        WHEN:  POST /api/v1/budgets/<uuid>/archive/
        THEN:  200 OK, budget is archived, its balance is moved to unallocated,
               and archived_at is set
        """
        budget = budget_factory(bank_account=account, balance=300)
        unalloc = account.unallocated_budget
        assert unalloc is not None
        unalloc_balance_before = unalloc.balance

        response = auth_client.post(
            reverse("api_v1:budget-archive", kwargs={"id": budget.id})
        )

        assert response.status_code == status.HTTP_200_OK
        check.is_true(response.data["archived"], "archived")
        check.is_not_none(response.data["archived_at"], "and records when")
        unalloc.refresh_from_db()
        check.equal(
            unalloc.balance,
            unalloc_balance_before + budget.balance,
            "balance moved to unallocated",
        )

    ####################################################################
    #
    def test_archive_also_archives_fillup_goal(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Recurring budget with a fill-up goal (both with balances)
        WHEN:  POST /api/v1/budgets/<uuid>/archive/
        THEN:  both the budget and its fill-up goal are archived, and both
               balances are moved to unallocated
        """
        budget = budget_factory(
            bank_account=account, budget_type="R", balance=200
        )
        budget.refresh_from_db()
        fillup = budget.fillup_goal
        assert fillup is not None
        fillup.balance = Money(100, "USD")
        fillup.save()
        unalloc = account.unallocated_budget
        assert unalloc is not None
        unalloc.refresh_from_db()
        unalloc_balance_before = unalloc.balance

        response = auth_client.post(
            reverse("api_v1:budget-archive", kwargs={"id": budget.id})
        )

        assert response.status_code == status.HTTP_200_OK
        fillup.refresh_from_db()
        check.is_true(fillup.archived, "fill-up goal archived")
        unalloc.refresh_from_db()
        check.equal(
            unalloc.balance,
            unalloc_balance_before + Money(300, "USD"),
            "both balances moved to unallocated",
        )

    ####################################################################
    #
    def test_create_recurring_creates_fillup_child(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an owned bank account
        WHEN:  POST /api/v1/budgets/ with budget_type=R
        THEN:  the response includes a fillup_goal UUID and an
               ASSOCIATED_FILLUP_GOAL child budget exists in the DB
        """
        response = auth_client.post(
            reverse("api_v1:budget-list"),
            {
                "name": "Eating Out",
                "bank_account": str(account.id),
                "budget_type": "R",
                "funding_type": "D",
                "target_balance": "300.00",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["fillup_goal"] is not None
        fillup = Budget.objects.get(id=response.data["fillup_goal"])
        check.equal(
            fillup.budget_type,
            Budget.BudgetType.ASSOCIATED_FILLUP_GOAL,
            "child is a fill-up goal",
        )
        check.equal(fillup.name, "Eating Out Fill-up", "named after parent")


########################################################################
########################################################################
#
class TestTransactionAPI:
    """Tests for the /api/v1/transactions/ endpoint."""

    ####################################################################
    #
    def test_create_transaction(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an owned bank account
        WHEN:  POST /api/v1/transactions/ with required fields
        THEN:  a transaction is created and a default allocation to
               the unallocated budget is auto-created
        """
        response = auth_client.post(
            reverse("api_v1:transaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "-45.99",
                "posted_date": "2026-04-01T12:00:00Z",
                "transaction_type": "signature_purchase",
                "raw_description": "GROCERY STORE #123",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        tx = Transaction.objects.get(id=response.data["id"])
        check.equal(tx.amount.amount, Decimal("-45.99"), "amount")
        check.equal(
            [
                a.budget
                for a in TransactionAllocation.objects.filter(transaction=tx)
            ],
            [account.unallocated_budget],
            "one allocation, to unallocated",
        )

    ####################################################################
    #
    def test_amount_immutable_after_create(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: an existing transaction
        WHEN:  PATCH with a new amount
        THEN:  400 Bad Request is returned
        """
        tx = transaction_factory(bank_account=account)

        response = auth_client.patch(
            reverse("api_v1:transaction-detail", kwargs={"id": tx.id}),
            {"amount": "999.99"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "amount" in response.data

    ####################################################################
    #
    def test_description_updatable(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: an existing transaction
        WHEN:  PATCH with a new description
        THEN:  the description is updated
        """
        tx = transaction_factory(bank_account=account)

        response = auth_client.patch(
            reverse("api_v1:transaction-detail", kwargs={"id": tx.id}),
            {"description": "Cleaned up description"},
        )

        assert response.status_code == status.HTTP_200_OK
        tx.refresh_from_db()
        assert tx.description == "Cleaned up description"

    ####################################################################
    #
    def test_pending_to_posted_updates_posted_balance(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending transaction on an account
        WHEN:  PATCH /api/v1/transactions/<uuid>/ with pending=False
        THEN:  the transaction is marked posted and the account's
               posted_balance is updated by the transaction amount
        """
        posted_balance_before = account.posted_balance
        tx = transaction_factory(
            bank_account=account,
            amount=Money(-50, get_default_currency()),
            pending=True,
        )
        account.refresh_from_db()
        # Pending transactions do not affect posted_balance.
        assert account.posted_balance == posted_balance_before

        response = auth_client.patch(
            reverse("api_v1:transaction-detail", kwargs={"id": tx.id}),
            {"pending": False},
        )

        assert response.status_code == status.HTTP_200_OK
        account.refresh_from_db()
        assert account.posted_balance == posted_balance_before + Money(
            -50, get_default_currency()
        )

    ####################################################################
    #
    def test_filter_by_date_range(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: transactions on different dates
        WHEN:  GET /api/v1/transactions/?date_from=...&date_to=...
        THEN:  only transactions in the range are returned
        """
        transaction_factory(
            bank_account=account, posted_date="2026-01-15T12:00:00Z"
        )
        in_range = transaction_factory(
            bank_account=account, posted_date="2026-03-15T12:00:00Z"
        )

        response = auth_client.get(
            reverse("api_v1:transaction-list"),
            {
                "date_from": "2026-03-01T00:00:00Z",
                "date_to": "2026-04-01T00:00:00Z",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert [t["id"] for t in response.data["results"]] == [str(in_range.id)]

    ####################################################################
    #
    def test_search_by_description(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: transactions with different descriptions
        WHEN:  GET /api/v1/transactions/?search=GROCERY
        THEN:  only matching transactions are returned
        """
        grocery = transaction_factory(
            bank_account=account, raw_description="GROCERY STORE #123"
        )
        transaction_factory(
            bank_account=account, raw_description="GAS STATION #456"
        )

        response = auth_client.get(
            reverse("api_v1:transaction-list"), {"search": "GROCERY"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert [t["id"] for t in response.data["results"]] == [str(grocery.id)]


####################################################################
#
@pytest.fixture
def ledger(
    account: BankAccount,
    unallocated: Budget,
    goal: Budget,
    make_goal: Callable[[], Budget],
    transaction_factory: Callable[..., Transaction],
) -> dict[str, Any]:
    """Transactions on `account` covering each way a row can be allocated.

    Returns:
        A dict of budgets ('unallocated', 'goal', 'other') and
        transactions: 'unassigned' (all on Unallocated), 'assigned'
        (all on `goal`), 'partial' ($40 of $100 on `goal`, the rest on
        Unallocated), 'pending' (pending, on Unallocated) and
        'elsewhere' (all on a second goal).
    """
    other = make_goal()

    def spend(raw_description: str, **kwargs: Any) -> Transaction:
        return transaction_factory(
            bank_account=account,
            amount=Money(-100, "USD"),
            raw_description=raw_description,
            **kwargs,
        )

    rows = {
        "unassigned": spend("UNASSIGNED SHOP"),
        "assigned": spend("ASSIGNED SHOP"),
        "partial": spend("PARTIAL SHOP"),
        "pending": spend("PENDING SHOP", pending=True),
        "elsewhere": spend("ELSEWHERE SHOP"),
    }
    transaction_svc.split(rows["assigned"], {str(goal.id): Decimal("100")})
    transaction_svc.split(rows["partial"], {str(goal.id): Decimal("40")})
    transaction_svc.split(rows["elsewhere"], {str(other.id): Decimal("100")})
    return {
        "unallocated": unallocated,
        "goal": goal,
        "other": other,
        **rows,
    }


####################################################################
#
@pytest.fixture
def make_rich_tx(
    account: BankAccount,
    goal: Budget,
    transaction_factory: Callable[..., Transaction],
    transaction_category_factory: Callable[..., TransactionCategory],
) -> Callable[[], Transaction]:
    """Return a factory for transactions that use every embedded relation.

    Each call makes a categorized transaction split between `goal` and
    Unallocated and linked to a counterpart transaction (both rows are
    on `account`).

    Returns:
        A callable `() -> Transaction`.
    """

    def _make() -> Transaction:
        counterpart = transaction_factory(bank_account=account)
        tx = transaction_factory(
            bank_account=account, amount=Money(-100, "USD")
        )
        tx.category = transaction_category_factory()
        tx.linked_transaction = counterpart
        tx.save(update_fields=["category", "linked_transaction"])
        transaction_svc.split(tx, {str(goal.id): Decimal("30")})
        return tx

    return _make


########################################################################
########################################################################
#
class TestTransactionListAllocations:
    """Budget filters and embedded allocations on /api/v1/transactions/."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "query, expected",
        [
            ({"budget": "goal"}, {"assigned", "partial"}),
            ({"budget": "unallocated"}, {"unassigned", "partial", "pending"}),
            ({"unallocated": "true"}, {"unassigned", "pending"}),
            ({"unallocated": "false"}, {"assigned", "partial", "elsewhere"}),
        ],
        ids=["budget", "unallocated_budget", "unallocated", "allocated"],
    )
    def test_filter(
        self,
        any_auth_client: APIClient,
        ledger: dict[str, Any],
        query: dict[str, str],
        expected: set[str],
    ) -> None:
        """
        GIVEN: transactions allocated in every way a row can be
        WHEN:  GET /api/v1/transactions/ with a budget or unallocated
               filter
        THEN:  exactly the matching transactions are returned, a
               partly assigned split counting as allocated
        """
        params = {
            key: str(ledger[value].id) if key == "budget" else value
            for key, value in query.items()
        }

        response = any_auth_client.get(
            reverse("api_v1:transaction-list"), params
        )

        assert response.status_code == status.HTTP_200_OK
        assert {r["id"] for r in response.data["results"]} == {
            str(ledger[name].id) for name in expected
        }

    ####################################################################
    #
    def test_budget_filter_with_search(
        self, auth_client: APIClient, ledger: dict[str, Any]
    ) -> None:
        """
        GIVEN: two transactions allocated to a goal
        WHEN:  GET /api/v1/transactions/?budget=<goal>&search=PARTIAL
        THEN:  only the goal's transaction matching the search is
               returned
        """
        response = auth_client.get(
            reverse("api_v1:transaction-list"),
            {"budget": str(ledger["goal"].id), "search": "PARTIAL"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert [r["id"] for r in response.data["results"]] == [
            str(ledger["partial"].id)
        ]

    ####################################################################
    #
    def test_budget_filtered_row_embeds_every_allocation(
        self, auth_client: APIClient, ledger: dict[str, Any]
    ) -> None:
        """
        GIVEN: a split transaction, $40 on a goal and $60 on Unallocated
        WHEN:  GET /api/v1/transactions/?budget=<goal>
        THEN:  its row embeds both allocations, not only the goal's
        """
        response = auth_client.get(
            reverse("api_v1:transaction-list"),
            {"budget": str(ledger["goal"].id)},
        )

        assert response.status_code == status.HTTP_200_OK
        row = next(
            r
            for r in response.data["results"]
            if r["id"] == str(ledger["partial"].id)
        )
        assert sorted(
            (a["budget"], Decimal(a["amount"])) for a in row["allocations"]
        ) == sorted(
            [
                (ledger["goal"].id, Decimal("-40")),
                (ledger["unallocated"].id, Decimal("-60")),
            ]
        )

    ####################################################################
    #
    def test_list_query_count_is_constant(
        self,
        auth_client: APIClient,
        make_rich_tx: Callable[[], Transaction],
    ) -> None:
        """
        GIVEN: categorized, linked, split transactions
        WHEN:  the transaction list is fetched, then fetched again after
               more such transactions are added
        THEN:  both fetches run the same number of queries
        """
        url = reverse("api_v1:transaction-list")
        make_rich_tx()
        with CaptureQueriesContext(connection) as few:
            assert auth_client.get(url).status_code == status.HTTP_200_OK
        for _ in range(3):
            make_rich_tx()
        with CaptureQueriesContext(connection) as many:
            response = auth_client.get(url)

        assert response.data["count"] == 8
        assert len(many) == len(few)


########################################################################
########################################################################
#
class TestTransactionAllocationAPI:
    """Tests for the /api/v1/allocations/ endpoint.

    The endpoint is read-only.  All allocation mutations (create,
    update, delete) must go through POST /api/v1/transactions/<id>/splits/.
    """

    ####################################################################
    #
    @pytest.fixture
    def allocation(
        self,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> TransactionAllocation:
        """An allocation to Unallocated on a transaction on `account`."""
        tx = transaction_factory(bank_account=account)
        return transaction_allocation_factory(
            transaction=tx, budget=account.unallocated_budget
        )

    ####################################################################
    #
    def test_list_returns_own_allocations(
        self,
        auth_client: APIClient,
        allocation: TransactionAllocation,
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: two allocations owned by the authenticated user
        WHEN:  GET /api/v1/allocations/
        THEN:  both allocations are returned
        """
        second = transaction_allocation_factory(
            transaction=allocation.transaction, budget=allocation.budget
        )

        response = auth_client.get(reverse("api_v1:transactionallocation-list"))

        assert response.status_code == status.HTTP_200_OK
        ids = {a["id"] for a in response.data["results"]}
        assert {str(allocation.id), str(second.id)} <= ids

    ####################################################################
    #
    def test_retrieve_allocation(
        self, auth_client: APIClient, allocation: TransactionAllocation
    ) -> None:
        """
        GIVEN: an existing allocation
        WHEN:  GET /api/v1/allocations/<id>/
        THEN:  200 OK with the allocation's data
        """
        response = auth_client.get(
            reverse(
                "api_v1:transactionallocation-detail",
                kwargs={"id": allocation.id},
            )
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(allocation.id)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method,use_detail",
        [
            ("post", False),
            ("put", True),
            ("patch", True),
            ("delete", True),
        ],
        ids=["post", "put", "patch", "delete"],
    )
    def test_mutation_methods_not_allowed(
        self,
        auth_client: APIClient,
        allocation: TransactionAllocation,
        method: str,
        use_detail: bool,
    ) -> None:
        """
        GIVEN: an existing allocation
        WHEN:  POST, PUT, PATCH, or DELETE is sent to the allocations endpoint
        THEN:  405 Method Not Allowed -- mutations go through /splits/
        """
        url = (
            reverse(
                "api_v1:transactionallocation-detail",
                kwargs={"id": allocation.id},
            )
            if use_detail
            else reverse("api_v1:transactionallocation-list")
        )

        response = getattr(auth_client, method)(url, {})

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


########################################################################
########################################################################
#
class TestTransactionSplitsAPI:
    """Tests for the POST /api/v1/transactions/<id>/splits/ endpoint."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "split_spec, expected_alloc_count, expected_balance_deltas",
        [
            # Two budgets, partial -- remainder to unallocated.
            (
                {"A": "50.00", "B": "30.00"},
                3,
                {"A": -50, "B": -30},
            ),
            # Two budgets, full amount -- no remainder.
            (
                {"A": "60.00", "B": "40.00"},
                2,
                {"A": -60, "B": -40},
            ),
            # Empty splits -- everything back to unallocated.
            ({}, 1, {}),
        ],
        ids=[
            "multi-with-remainder",
            "multi-exact",
            "empty-to-unallocated",
        ],
    )
    def test_splits_reconciliation(
        self,
        auth_client: APIClient,
        account: BankAccount,
        spent_tx: Transaction,
        budget_factory: Callable[..., Budget],
        split_spec: dict[str, str],
        expected_alloc_count: int,
        expected_balance_deltas: dict[str, int],
    ) -> None:
        """
        GIVEN: a -100 transaction with one unallocated allocation and
               two budgets (A, B) each starting at $500
        WHEN:  POST splits with the given split_spec
        THEN:  the expected number of allocations exist with correct
               amounts, and budget balances reflect the deltas
        """
        budgets = {
            "A": budget_factory(
                bank_account=account, balance=Money(500, "USD")
            ),
            "B": budget_factory(
                bank_account=account, balance=Money(500, "USD")
            ),
        }
        unalloc = account.unallocated_budget
        assert unalloc is not None
        unalloc.refresh_from_db()
        unalloc_before = unalloc.balance
        # Map symbolic keys ("A", "B") to real budget UUIDs.
        request_splits = {str(budgets[k].id): v for k, v in split_spec.items()}

        response = auth_client.post(
            _splits_url(spent_tx), {"splits": request_splits}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        check.equal(len(response.data), expected_alloc_count, "allocations")

        by_budget = {str(a["budget"]): a for a in response.data}
        for key, amount_str in split_spec.items():
            check.equal(
                Decimal(by_budget[str(budgets[key].id)]["amount"]),
                Decimal(f"-{amount_str}"),
                f"allocation to {key}",
            )

        split_total = sum(Decimal(v) for v in split_spec.values())
        remainder = Decimal("100") - split_total
        if remainder > 0:
            check.equal(
                Decimal(by_budget[str(unalloc.id)]["amount"]),
                -remainder,
                "remainder allocated to unallocated",
            )

        for key, delta in expected_balance_deltas.items():
            budgets[key].refresh_from_db()
            check.equal(
                budgets[key].balance,
                Money(500 + delta, "USD"),
                f"budget {key} balance",
            )

        # Unallocated gets back everything that is now split elsewhere.
        unalloc.refresh_from_db()
        check.equal(
            unalloc.balance,
            unalloc_before + Money(split_total, "USD"),
            "unallocated balance",
        )

        # Each returned allocation is the only allocation for its budget
        # here, so its budget_balance snapshot must equal the budget's
        # current balance.
        for alloc_data in response.data:
            budget_in_db = Budget.objects.get(id=alloc_data["budget"])
            check.equal(
                Decimal(alloc_data["budget_balance"]),
                budget_in_db.balance.amount,
                f"budget_balance snapshot for {alloc_data['budget']}",
            )

    ####################################################################
    #
    def test_splits_exceeding_transaction_rejected(
        self,
        auth_client: APIClient,
        account: BankAccount,
        spent_tx: Transaction,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a -100 transaction
        WHEN:  POST splits totalling 150
        THEN:  400 Bad Request -- the split exceeds the transaction
        """
        budget = budget_factory(bank_account=account)

        response = auth_client.post(
            _splits_url(spent_tx),
            {"splits": {str(budget.id): "150.00"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "exceeds transaction amount" in str(response.data)

    ####################################################################
    #
    def test_unknown_budget_rejected(
        self, auth_client: APIClient, spent_tx: Transaction
    ) -> None:
        """
        GIVEN: a transaction
        WHEN:  POST splits with a non-existent budget UUID
        THEN:  400 Bad Request -- unknown budget
        """
        response = auth_client.post(
            _splits_url(spent_tx),
            {"splits": {"00000000-0000-0000-0000-000000000000": "50.00"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Unknown budget IDs" in str(response.data)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "same_owner",
        [True, False],
        ids=["same-owner-different-account", "different-owner"],
    )
    def test_cross_account_budget_rejected(
        self,
        auth_client: APIClient,
        user: User,
        user_factory: Callable[..., User],
        spent_tx: Transaction,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        same_owner: bool,
    ) -> None:
        """
        GIVEN: a transaction on account A and a budget on account B
               (B owned by the same user or a different user)
        WHEN:  POST splits referencing the cross-account budget
        THEN:  400 Bad Request -- budget must be in the same account
        """
        other_owner = user if same_owner else user_factory()
        other_account = bank_account_factory(owners=[other_owner])
        budget_b = budget_factory(bank_account=other_account)

        response = auth_client.post(
            _splits_url(spent_tx),
            {"splits": {str(budget_b.id): "50.00"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "do not belong to the same bank account" in str(response.data)

    ####################################################################
    #
    def test_resplit_updates_existing_allocations(
        self,
        auth_client: APIClient,
        account: BankAccount,
        spent_tx: Transaction,
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a -100 transaction split 60/40 across two budgets
        WHEN:  POST splits changing to 70/30
        THEN:  allocations are updated in place, budget balances
               reflect the change
        """
        budget_a = budget_factory(
            bank_account=account, balance=Money(500, "USD")
        )
        budget_b = budget_factory(
            bank_account=account, balance=Money(500, "USD")
        )
        transaction_allocation_factory(
            transaction=spent_tx, budget=budget_a, amount=Money(-60, "USD")
        )
        transaction_allocation_factory(
            transaction=spent_tx, budget=budget_b, amount=Money(-40, "USD")
        )

        response = auth_client.post(
            _splits_url(spent_tx),
            {"splits": {str(budget_a.id): "70.00", str(budget_b.id): "30.00"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        check.equal(len(response.data), 2, "two allocations")
        budget_a.refresh_from_db()
        budget_b.refresh_from_db()
        check.equal(budget_a.balance, Money(430, "USD"), "A balance")
        check.equal(budget_b.balance, Money(470, "USD"), "B balance")

    ####################################################################
    #
    def test_splits_on_past_transaction_propagates_running_balances(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: budget X with two allocations -- T1 (Jan 1, +$50) then
               T2 (Jan 15, +$30) -- so running balances are $50 and $80
        WHEN:  POST splits on T1 changes X's share from $50 to $20
        THEN:  T1's budget_balance snapshot becomes $20 and T2's
               downstream snapshot is propagated forward to $50
               (not left as a stale $80)
        """
        budget_x = budget_factory(bank_account=account, balance=Money(0, "USD"))
        t1 = transaction_factory(
            bank_account=account,
            amount=Money(50, "USD"),
            posted_date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        a1 = transaction_allocation_factory(
            transaction=t1, budget=budget_x, amount=Money(50, "USD")
        )
        t2 = transaction_factory(
            bank_account=account,
            amount=Money(30, "USD"),
            posted_date=datetime(2024, 1, 15, tzinfo=UTC),
        )
        a2 = transaction_allocation_factory(
            transaction=t2, budget=budget_x, amount=Money(30, "USD")
        )
        a1.refresh_from_db()
        a2.refresh_from_db()
        assert (a1.budget_balance, a2.budget_balance) == (
            Money(50, "USD"),
            Money(80, "USD"),
        )

        # Re-split T1: $20 to X, remainder to unallocated.
        response = auth_client.post(
            _splits_url(t1),
            {"splits": {str(budget_x.id): "20.00"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        a1.refresh_from_db()
        a2.refresh_from_db()
        budget_x.refresh_from_db()
        check.equal(a1.amount, Money(20, "USD"), "T1 allocation updated")
        check.equal(
            a1.budget_balance, Money(20, "USD"), "T1 snapshot reflects it"
        )
        check.equal(
            a2.budget_balance,
            Money(50, "USD"),
            "T2 snapshot propagated forward (20 + 30)",
        )
        check.equal(
            budget_x.balance, Money(50, "USD"), "X balance is the final total"
        )


########################################################################
########################################################################
#
class TestRunningBalanceWithInternalTransactions:
    """Verify that budget_balance snapshots on TransactionAllocations
    account for InternalTransaction top-ups that occur between
    allocations chronologically.

    These tests mimic the backfill_budget command flow:

    1. Bank account starts with enough available_balance so
       the auto-created Unallocated budget has funds.
    2. Transactions are imported first -- each gets an allocation
       to Unallocated (the import pipeline's behavior).
    3. An InternalTransaction funds the target budget from
       Unallocated (the monthly top-up).
    4. The splits API moves each allocation from Unallocated
       to the target budget (the interactive allocation step).
    5. At a month boundary another InternalTransaction top-up
       occurs, then more splits follow.
    """

    ####################################################################
    #
    def test_backfill_flow_running_balances(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: a bank account with $5000 available, 10 imported
               transactions (each allocated to Unallocated),
               and a recurring budget with $0 starting balance
        WHEN:  the backfill flow runs --
                 1. fund budget to $500 from Unallocated
                 2. split 5 January transactions to the budget
                 3. fund budget back to $500 from Unallocated
                 4. split 5 February transactions to the budget
        THEN:  every allocation's budget_balance snapshot
               correctly reflects both the allocation amounts
               AND the InternalTransaction funding that
               preceded it

        Timeline (mimics backfill_budget month-by-month):
            Step 1:  InternalTransaction +$500 Unallocated -> budget
            Step 2:  Split T1..T5 (-$40 each) to budget
            Step 3:  InternalTransaction +$200 Unallocated -> budget
                     (top up from $300 back to $500)
            Step 4:  Split T6..T10 (-$40 each) to budget

        Expected running budget_balance after each split:
            T1..T5:  460, 420, 380, 340, 300
            -- InternalTransaction +200 -> balance now 500 --
            T6..T10: 460, 420, 380, 340, 300

        Final budget balance: $300
        """
        # -- Setup: bank account with $5000 so Unallocated starts
        # with enough to cover all funding and transactions. --
        account = bank_account_factory(
            owners=[user],
            available_balance=Money(5000, "USD"),
            posted_balance=Money(5000, "USD"),
        )
        unalloc = account.unallocated_budget
        assert unalloc is not None
        assert unalloc.balance == Money(5000, "USD")
        budget = budget_factory(bank_account=account, balance=Money(0, "USD"))

        # -- Step 0: Import all 10 transactions up front. --
        # Each gets an allocation to Unallocated, just like the
        # import pipeline does.
        imported_txs = []
        for i in range(10):
            tx = transaction_factory(
                bank_account=account,
                amount=Money(-40, "USD"),
                posted_date=datetime(2024, 1, i + 1, tzinfo=UTC),
            )
            transaction_allocation_factory(
                transaction=tx, budget=unalloc, amount=Money(-40, "USD")
            )
            imported_txs.append(tx)

        ################################################################
        #
        def top_up(amount: int, effective_date: datetime) -> None:
            unalloc.refresh_from_db()
            internal_transaction_factory(
                bank_account=account,
                src_budget=unalloc,
                dst_budget=budget,
                amount=Money(amount, "USD"),
                actor=user,
                effective_date=effective_date,
            )

        ################################################################
        #
        def split_all_to_budget(txs: list[Transaction], first: int) -> None:
            for n, tx in enumerate(txs, start=first):
                response = auth_client.post(
                    _splits_url(tx),
                    {"splits": {str(budget.id): "40.00"}},
                    format="json",
                )
                assert response.status_code == status.HTTP_200_OK
                snapshots = [
                    Decimal(a["budget_balance"])
                    for a in response.data
                    if str(a["budget"]) == str(budget.id)
                ]
                check.equal(
                    snapshots,
                    [Decimal(500 - 40 * (n - first + 1))],
                    f"split {n} budget_balance",
                )

        # -- Step 1: Initial funding -- top budget up to $500. --
        # effective_date is before the first transaction (Jan 1 midnight)
        # so the ITx slots before T1 in the running-balance timeline.
        top_up(500, datetime(2024, 1, 1, tzinfo=UTC))
        budget.refresh_from_db()
        assert budget.balance == Money(500, "USD")

        # -- Step 2: Split first 5 transactions to the budget. --
        split_all_to_budget(imported_txs[:5], first=1)
        budget.refresh_from_db()
        check.equal(budget.balance, Money(300, "USD"), "after first batch")

        # -- Step 3: Top-up -- fund back to $500. --
        # effective_date is Jan 6 midnight so the ITx slots after T5
        # (Jan 5) and is captured in T6's window (Jan 6).
        top_up(200, datetime(2024, 1, 6, tzinfo=UTC))
        budget.refresh_from_db()
        check.equal(budget.balance, Money(500, "USD"), "after top-up")

        # -- Step 4: Split remaining 5 transactions. --
        split_all_to_budget(imported_txs[5:], first=6)
        budget.refresh_from_db()
        check.equal(budget.balance, Money(300, "USD"), "final balance")


########################################################################
########################################################################
#
class TestResolvePendingAPI:
    """Tests for POST /api/v1/transactions/<id>/resolve-pending/."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "pending_amount, payload_extra, expected_final, expected_avail_delta",
        [
            # Same amount: no amount in payload, available_balance unchanged.
            (Money(-60, "USD"), {}, Money(-60, "USD"), Money(0, "USD")),
            # Amount changed -$100 -> -$95: available adjusts by +$5.
            (
                Money(-100, "USD"),
                {"amount": "-95.00", "amount_currency": "USD"},
                Money(-95, "USD"),
                Money(5, "USD"),
            ),
        ],
        ids=["same_amount", "amount_changed"],
    )
    def test_resolve_pending(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        pending_amount: Money,
        payload_extra: dict,
        expected_final: Money,
        expected_avail_delta: Money,
    ) -> None:
        """
        GIVEN: a pending transaction
        WHEN:  POST resolve-pending (optionally with a new amount)
        THEN:  200, pending cleared, posted_balance credited by final amount,
               available_balance adjusted by the delta
        """
        account = bank_account_factory(
            owners=[user],
            available_balance=Money(1000, "USD"),
            posted_balance=Money(1000, "USD"),
        )
        tx = transaction_svc.create(
            bank_account=account,
            amount=pending_amount,
            posted_date=datetime(2026, 5, 1, tzinfo=UTC),
            raw_description="PENDING CHARGE",
            pending=True,
        )
        account.refresh_from_db()
        avail_before = account.available_balance
        posted_before = account.posted_balance

        response = auth_client.post(
            reverse("api_v1:transaction-resolve-pending", kwargs={"id": tx.id}),
            {"posted_date": "2026-05-03T00:00:00Z", **payload_extra},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        check.is_false(response.data["pending"], "no longer pending")
        check.equal(
            Decimal(response.data["amount"]),
            expected_final.amount,
            "final amount",
        )
        check.equal(
            [Decimal(a["amount"]) for a in response.data["allocations"]],
            [expected_final.amount],
            "embedded allocation carries the final amount",
        )
        account.refresh_from_db()
        check.equal(
            account.available_balance,
            avail_before + expected_avail_delta,
            "available balance adjusted by the delta",
        )
        check.equal(
            account.posted_balance,
            posted_before + expected_final,
            "posted balance credited the final amount",
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "pending, payload_extra",
        [
            # Already-posted transaction.
            (False, {}),
            # Wrong sign: debit supplied with a credit amount.
            (True, {"amount": "50.00", "amount_currency": "USD"}),
        ],
        ids=["already_posted", "wrong_sign"],
    )
    def test_resolve_pending_rejected(
        self,
        auth_client: APIClient,
        account: BankAccount,
        pending: bool,
        payload_extra: dict,
    ) -> None:
        """
        GIVEN: an invalid resolve-pending request (already posted, or wrong sign)
        WHEN:  POST resolve-pending
        THEN:  400 Bad Request
        """
        tx = transaction_svc.create(
            bank_account=account,
            amount=Money(-50, "USD"),
            posted_date=datetime(2026, 5, 1, tzinfo=UTC),
            raw_description="CHARGE",
            pending=pending,
        )

        response = auth_client.post(
            reverse("api_v1:transaction-resolve-pending", kwargs={"id": tx.id}),
            {"posted_date": "2026-05-03T00:00:00Z", **payload_extra},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


########################################################################
########################################################################
#
class TestInternalTransactionAPI:
    """Tests for the /api/v1/internal-transactions/ endpoint."""

    ####################################################################
    #
    def test_create_internal_transaction(
        self,
        auth_client: APIClient,
        user: User,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an owned account with two budgets
        WHEN:  POST /api/v1/internal-transactions/ with amount, src, dst
        THEN:  the transfer is created and the actor is set to the user
        """
        src = budget_factory(bank_account=account, balance=Money(500, "USD"))
        dst = budget_factory(bank_account=account)

        response = auth_client.post(
            reverse("api_v1:internaltransaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "100.00",
                "src_budget": str(src.id),
                "dst_budget": str(dst.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        itx = InternalTransaction.objects.get(id=response.data["id"])
        assert itx.actor == user

    ####################################################################
    #
    def test_same_src_dst_rejected(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a single budget
        WHEN:  POST with src_budget == dst_budget
        THEN:  400 Bad Request is returned
        """
        budget = budget_factory(bank_account=account)

        response = auth_client.post(
            reverse("api_v1:internaltransaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "50.00",
                "src_budget": str(budget.id),
                "dst_budget": str(budget.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    @pytest.mark.parametrize(
        ("which_cross", "same_owner"),
        [
            ("src", True),
            ("dst", True),
            ("src", False),
            ("dst", False),
        ],
        ids=[
            "src-same-owner",
            "dst-same-owner",
            "src-different-owner",
            "dst-different-owner",
        ],
    )
    def test_cross_account_budget_rejected(
        self,
        auth_client: APIClient,
        user: User,
        account: BankAccount,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        which_cross: str,
        same_owner: bool,
    ) -> None:
        """
        GIVEN: two bank accounts (same or different owner) with
               budgets on each
        WHEN:  POST an internal transaction whose src or dst budget
               belongs to a different account than bank_account
        THEN:  400 Bad Request
        """
        other_owner = user if same_owner else user_factory()
        other_account = bank_account_factory(owners=[other_owner])
        budget_here = budget_factory(bank_account=account)
        budget_there = budget_factory(bank_account=other_account)
        src, dst = (
            (budget_there, budget_here)
            if which_cross == "src"
            else (budget_here, budget_there)
        )

        response = auth_client.post(
            reverse("api_v1:internaltransaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "50.00",
                "src_budget": str(src.id),
                "dst_budget": str(dst.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    @pytest.mark.parametrize("method", ["patch", "delete"])
    def test_update_and_delete_not_allowed(
        self,
        auth_client: APIClient,
        user: User,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
        method: str,
    ) -> None:
        """
        GIVEN: an existing internal transaction
        WHEN:  PATCH or DELETE /api/v1/internal-transactions/<uuid>/
        THEN:  405 Method Not Allowed is returned
        """
        itx = internal_transaction_factory(
            bank_account=account,
            src_budget=budget_factory(
                bank_account=account, balance=Money(500, "USD")
            ),
            dst_budget=budget_factory(bank_account=account),
            actor=user,
        )
        url = reverse(
            "api_v1:internaltransaction-detail", kwargs={"id": itx.id}
        )

        response = getattr(auth_client, method)(url)

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


########################################################################
########################################################################
#
class TestPermissions:
    """Tests for ownership-based access control across all endpoints.

    The AccountOwnerQuerySetMixin has three code paths based on
    model type: BankAccount (owners=user), Budget/Transaction
    (bank_account__owners=user), and TransactionAllocation
    (transaction__bank_account__owners=user).  Each is tested here.

    NOTE: The parametrized factory_cls values are factory classes called
    directly because pytest_factoryboy fixtures cannot be used inside
    parametrize. This is the one place where direct factory calls are
    acceptable.
    """

    ####################################################################
    #
    @pytest.mark.parametrize(
        "factory_cls, detail_url_name",
        [
            (BankAccountFactory, "api_v1:bankaccount-detail"),
            (BudgetFactory, "api_v1:budget-detail"),
            (TransactionFactory, "api_v1:transaction-detail"),
        ],
        ids=["account", "budget", "transaction"],
    )
    @pytest.mark.parametrize(
        "is_staff, is_superuser",
        [
            (False, False),
            (True, True),
        ],
        ids=["regular", "staff-superuser"],
    )
    def test_cannot_retrieve_other_users_object(
        self,
        auth_client: APIClient,
        user: User,
        is_staff: bool,
        is_superuser: bool,
        factory_cls: type,
        detail_url_name: str,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an object belonging to another user's account
        WHEN:  GET /api/v1/<resource>/<uuid>/
        THEN:  404 Not Found -- ownership filtering is not bypassed by
               staff or superuser privilege
        """
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save()
        other_account = bank_account_factory()
        obj = (
            other_account
            if factory_cls is BankAccountFactory
            else factory_cls(bank_account=other_account)
        )

        response = auth_client.get(
            reverse(detail_url_name, kwargs={"id": obj.id})
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


########################################################################
########################################################################
#
class TestAPIKeyAuthParity:
    """An API key must see exactly the same domain data a JWT session for
    the same user sees.  Complements the status-code-only checks in
    tests.users.test_api_keys.TestRequiresInteractiveAuth, which cover
    that machine credentials are denied on user/security endpoints and
    allowed on domain endpoints, but don't check response payloads.
    """

    ####################################################################
    #
    def test_api_key_and_jwt_return_identical_account_data(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        make_api_key_client: Callable[..., APIClient],
    ) -> None:
        """
        GIVEN: a user with several bank accounts, and an API key for
               that same user
        WHEN:  GET /api/v1/bank-accounts/ is made once via a JWT
               session and once via the API key
        THEN:  both responses return the identical set of accounts,
               field-for-field
        """
        for _ in range(3):
            bank_account_factory(owners=[user])
        key_client = make_api_key_client(user, "parity check")
        url = reverse("api_v1:bankaccount-list")

        jwt_response = auth_client.get(url)
        key_response = key_client.get(url)

        assert jwt_response.status_code == status.HTTP_200_OK
        assert key_response.status_code == status.HTTP_200_OK
        # Compare by id rather than assuming identical list ordering
        # across the two separate requests.
        jwt_by_id = {a["id"]: a for a in jwt_response.data["results"]}
        key_by_id = {a["id"]: a for a in key_response.data["results"]}
        check.equal(len(jwt_by_id), 3, "all three accounts")
        check.equal(jwt_by_id, key_by_id, "identical through both clients")


########################################################################
########################################################################
#
# Dataset layout built by `occurrence_dataset`:
#
#   a1 (owned) -+- b1 --- occ1  FUND   2026-01-01  PENDING
#               |          occ2  RECUR  2026-02-01  PARTIAL
#               +- b2 --- occ3  FUND   2026-02-01  COMPLETE
#   a2 (owned) --- b3 --- occ4  RECUR  2026-03-01  SKIPPED
#
_FILTER_CASES = [
    pytest.param({"budget": "b1"}, {"occ1", "occ2"}, id="budget"),
    pytest.param({"bank_account": "a2"}, {"occ4"}, id="bank-account"),
    pytest.param({"kind": "fund"}, {"occ1", "occ3"}, id="kind-fund"),
    pytest.param({"kind": "recur"}, {"occ2", "occ4"}, id="kind-recur"),
    pytest.param({"status": "PENDING"}, {"occ1"}, id="status-single"),
    pytest.param(
        {"status": ["PENDING", "PARTIAL"]}, {"occ1", "occ2"}, id="status-multi"
    ),
    pytest.param(
        {"date_from": "2026-01-15", "date_to": "2026-02-28"},
        {"occ2", "occ3"},
        id="date-range",
    ),
]


class TestFundingEventOccurrenceAPI:
    """Tests for the /api/v1/funding-occurrences/ endpoint."""

    ####################################################################
    #
    @pytest.fixture
    def foreign_occurrence(
        self,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        funding_event_occurrence_factory: Callable[..., FundingEventOccurrence],
    ) -> FundingEventOccurrence:
        """A funding occurrence on another user's account."""
        other_account = bank_account_factory(owners=[user_factory()])
        return funding_event_occurrence_factory(
            budget=budget_factory(bank_account=other_account)
        )

    ####################################################################
    #
    @pytest.fixture
    def occurrence_dataset(
        self,
        user: User,
        account: BankAccount,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        funding_event_occurrence_factory: Callable[..., FundingEventOccurrence],
    ) -> dict[str, Any]:
        """The accounts, budgets and occurrences drawn above, by name."""
        a2 = bank_account_factory(owners=[user])
        b1 = budget_factory(bank_account=account)
        b2 = budget_factory(bank_account=account)
        b3 = budget_factory(bank_account=a2)
        occurrences = {
            name: funding_event_occurrence_factory(
                budget=budget,
                kind=kind.value,
                scheduled_date=scheduled,
                status=occ_status,
            )
            for name, budget, kind, scheduled, occ_status in [
                (
                    "occ1",
                    b1,
                    EventKind.FUND,
                    date(2026, 1, 1),
                    FundingEventOccurrence.Status.PENDING,
                ),
                (
                    "occ2",
                    b1,
                    EventKind.RECUR,
                    date(2026, 2, 1),
                    FundingEventOccurrence.Status.PARTIAL,
                ),
                (
                    "occ3",
                    b2,
                    EventKind.FUND,
                    date(2026, 2, 1),
                    FundingEventOccurrence.Status.COMPLETE,
                ),
                (
                    "occ4",
                    b3,
                    EventKind.RECUR,
                    date(2026, 3, 1),
                    FundingEventOccurrence.Status.SKIPPED,
                ),
            ]
        }
        return {"a1": account, "a2": a2, "b1": b1, "b2": b2, "b3": b3} | (
            occurrences
        )

    ####################################################################
    #
    def test_non_owner_excluded_from_list(
        self,
        auth_client: APIClient,
        foreign_occurrence: FundingEventOccurrence,
    ) -> None:
        """
        GIVEN: a funding occurrence on another user's account
        WHEN:  GET /api/v1/funding-occurrences/
        THEN:  the occurrence does not appear in the results
        """
        response = auth_client.get(reverse("api_v1:funding-occurrence-list"))

        assert response.status_code == status.HTTP_200_OK
        assert str(foreign_occurrence.id) not in {
            r["id"] for r in response.data["results"]
        }

    ####################################################################
    #
    def test_non_owner_retrieve_returns_404(
        self,
        auth_client: APIClient,
        foreign_occurrence: FundingEventOccurrence,
    ) -> None:
        """
        GIVEN: a funding occurrence on another user's account
        WHEN:  GET /api/v1/funding-occurrences/<uuid>/
        THEN:  404 Not Found
        """
        response = auth_client.get(
            reverse(
                "api_v1:funding-occurrence-detail",
                kwargs={"id": foreign_occurrence.id},
            )
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    ####################################################################
    #
    def test_retrieve_own_occurrence(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
        funding_event_occurrence_factory: Callable[..., FundingEventOccurrence],
    ) -> None:
        """
        GIVEN: a funding occurrence on an owned budget
        WHEN:  GET /api/v1/funding-occurrences/<uuid>/
        THEN:  200 OK with all expected fields
        """
        budget = budget_factory(bank_account=account)
        occ = funding_event_occurrence_factory(
            budget=budget,
            kind=EventKind.FUND.value,
            scheduled_date=date(2026, 3, 15),
            status=FundingEventOccurrence.Status.PARTIAL,
        )

        response = auth_client.get(
            reverse("api_v1:funding-occurrence-detail", kwargs={"id": occ.id})
        )

        assert response.status_code == status.HTTP_200_OK
        check.equal(response.data["id"], str(occ.id), "id")
        check.equal(response.data["budget"], str(budget.id), "budget")
        check.equal(response.data["kind"], EventKind.FUND.value, "kind")
        check.equal(response.data["scheduled_date"], "2026-03-15", "date")
        check.equal(
            response.data["status"],
            FundingEventOccurrence.Status.PARTIAL,
            "status",
        )
        check.is_none(response.data["completed_at"], "not completed")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method,use_detail",
        [
            ("post", False),
            ("put", True),
            ("patch", True),
            ("delete", True),
        ],
        ids=["post", "put", "patch", "delete"],
    )
    def test_mutation_methods_not_allowed(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
        funding_event_occurrence_factory: Callable[..., FundingEventOccurrence],
        method: str,
        use_detail: bool,
    ) -> None:
        """
        GIVEN: an existing funding occurrence
        WHEN:  POST, PUT, PATCH, or DELETE is sent to the endpoint
        THEN:  405 Method Not Allowed
        """
        occ = funding_event_occurrence_factory(
            budget=budget_factory(bank_account=account)
        )
        url = (
            reverse("api_v1:funding-occurrence-detail", kwargs={"id": occ.id})
            if use_detail
            else reverse("api_v1:funding-occurrence-list")
        )

        response = getattr(auth_client, method)(url, {})

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    ####################################################################
    #
    @pytest.mark.parametrize("raw_params,expected_names", _FILTER_CASES)
    def test_filter(
        self,
        auth_client: APIClient,
        occurrence_dataset: dict[str, Any],
        raw_params: dict,
        expected_names: set[str],
    ) -> None:
        """
        GIVEN: four occurrences spread across two accounts and three budgets
        WHEN:  GET /api/v1/funding-occurrences/ with a filter parameter
        THEN:  only the matching occurrences are returned
        """

        def resolve(v: object) -> object:
            if isinstance(v, list):
                return [resolve(x) for x in v]
            if isinstance(v, str) and v in occurrence_dataset:
                return str(occurrence_dataset[v].id)
            return v

        params = {k: resolve(v) for k, v in raw_params.items()}
        expected_ids = {str(occurrence_dataset[n].id) for n in expected_names}

        response = auth_client.get(
            reverse("api_v1:funding-occurrence-list"), params
        )

        assert response.status_code == status.HTTP_200_OK
        assert {r["id"] for r in response.data["results"]} == expected_ids

    ####################################################################
    #
    def test_default_ordering_newest_first(
        self,
        auth_client: APIClient,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
        funding_event_occurrence_factory: Callable[..., FundingEventOccurrence],
    ) -> None:
        """
        GIVEN: occurrences with different scheduled dates
        WHEN:  GET /api/v1/funding-occurrences/ with no ordering param
        THEN:  results are ordered newest scheduled_date first
        """
        budget = budget_factory(bank_account=account)
        early = funding_event_occurrence_factory(
            budget=budget, scheduled_date=date(2026, 1, 1)
        )
        middle = funding_event_occurrence_factory(
            budget=budget,
            kind=EventKind.RECUR.value,
            scheduled_date=date(2026, 2, 1),
        )
        late = funding_event_occurrence_factory(
            budget=budget_factory(bank_account=account),
            scheduled_date=date(2026, 3, 1),
        )

        response = auth_client.get(reverse("api_v1:funding-occurrence-list"))

        assert response.status_code == status.HTTP_200_OK
        returned_ids = [r["id"] for r in response.data["results"]]
        late_idx = returned_ids.index(str(late.id))
        mid_idx = returned_ids.index(str(middle.id))
        early_idx = returned_ids.index(str(early.id))
        assert late_idx < mid_idx < early_idx


########################################################################
########################################################################
#
class TestRunFundingEndpoint:
    """POST /api/v1/bank-accounts/<id>/run-funding/"""

    ####################################################################
    #
    def _url(self, account: BankAccount) -> str:
        return reverse(
            "api_v1:bankaccount-run-funding", kwargs={"id": str(account.id)}
        )

    ####################################################################
    #
    def test_returns_409_when_nothing_due(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: an account with no due funding events (no budgets with schedules)
        WHEN:  POST run-funding
        THEN:  409 Conflict -- nothing to do
        """
        response = auth_client.post(self._url(account))
        assert response.status_code == status.HTTP_409_CONFLICT

    ####################################################################
    #
    def test_auto_funding_disabled_account_still_runs(
        self,
        auth_client: APIClient,
        account: BankAccount,
        make_scheduled_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an account with auto_funding_enabled=False and a due FUND event
        WHEN:  POST run-funding (manual trigger)
        THEN:  200 -- the toggle only blocks scheduled tasks, not manual runs
        """
        account.auto_funding_enabled = False
        account.save(update_fields=["auto_funding_enabled"])
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )
        # The pointer sits before the first schedule occurrence, so a
        # FUND event is due immediately.
        make_scheduled_budget(
            last_funded_on=date(2026, 1, 1), funding_amount=Money(50, "USD")
        )
        account.refresh_from_db()
        assert account.auto_funding_enabled is False

        response = auth_client.post(self._url(account))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["transfers"] >= 1
