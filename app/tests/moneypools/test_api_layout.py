"""Tests for the public import surface and routed actions of the v1 API.

`moneypools.api.v1.views` and `moneypools.api.v1.serializers` are
packages of per-domain modules whose `__init__` re-exports every name
the former single-file modules exposed.  `BankAccountViewSet` composes
its `@action` endpoints from per-concern mixins.  These tests pin both
contracts: the re-exported names, and the actions DRF routes on
`BankAccountViewSet` with their URL paths, HTTP methods and the
interactive-auth gate on the invitation actions.

The name lists are plain module constants because they feed
`pytest.mark.parametrize`, which is evaluated before fixtures exist.
"""

# system imports
from types import ModuleType

# 3rd party imports
import pytest
import pytest_check as check

# Project imports
from moneypools.api.v1 import serializers as v1_serializers
from moneypools.api.v1 import views as v1_views
from moneypools.api.v1.views import BankAccountViewSet
from moneypools.api.v1.views.funding import BankAccountFundingActions
from moneypools.api.v1.views.imports import BankAccountImportActions
from moneypools.api.v1.views.invitations import BankAccountInvitationActions
from users.permissions import RequiresInteractiveAuth

VIEW_NAMES = [
    "BankViewSet",
    "BankAccountViewSet",
    "BudgetViewSet",
    "TransactionCategoryViewSet",
    "TransactionViewSet",
    "TransactionAllocationViewSet",
    "InternalTransactionViewSet",
    "FundingEventOccurrenceViewSet",
    "currencies",
    "invitation_detail",
    "invitation_accept",
    "invitation_decline",
]

SERIALIZER_NAMES = [
    "RecurrenceSerializerField",
    "BankSerializer",
    "BankAccountSerializer",
    "TransactionCategorySerializer",
    "BudgetSerializer",
    "TransactionSerializer",
    "TransactionAllocationSerializer",
    "TransactionSplitsSerializer",
    "InternalTransactionSerializer",
    "ResolvePendingSerializer",
    "ScrapeSyncTransactionSerializer",
    "ScrapeSyncSerializer",
    "ScrapeSyncDetailsNeededSerializer",
    "ScrapeSyncReportSerializer",
    "TransactionDetailsItemSerializer",
    "TransactionDetailsSerializer",
    "TransactionDetailsResultSerializer",
    "TransactionDetailsReportSerializer",
    "FundingEventOccurrenceSerializer",
    "BankAccountInvitationSerializer",
    "InviteOwnerSerializer",
    "PublicInvitationDetailSerializer",
]

# Action name -> (url_path, HTTP methods) as routed under
# `/api/v1/bank-accounts/<id>/`.
#
BANK_ACCOUNT_ACTIONS = {
    "mark_imported": ("mark-imported", {"post"}),
    "sync_scrape": ("sync-scrape", {"post"}),
    "transaction_details": ("transaction-details", {"post"}),
    "run_funding": ("run-funding", {"post"}),
    "funding_event_dates": ("funding-event-dates", {"get"}),
    "funding_summary": ("funding-summary", {"get"}),
    "invite": ("invite", {"post"}),
    "invitations": ("invitations", {"get"}),
    "cancel_invitation": (
        r"invitations/(?P<token>[^/.]+)/cancel",
        {"post"},
    ),
}

INVITATION_ACTIONS = ["invite", "invitations", "cancel_invitation"]


########################################################################
########################################################################
#
class TestPublicImportSurface:
    """The v1 packages re-export every name the old modules exposed."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "module,names",
        [
            pytest.param(v1_views, VIEW_NAMES, id="views"),
            pytest.param(v1_serializers, SERIALIZER_NAMES, id="serializers"),
        ],
    )
    def test_package_exports_former_module_names(
        self, module: ModuleType, names: list[str]
    ) -> None:
        """
        GIVEN: the names the former `views.py` and `serializers.py`
               modules defined
        WHEN:  the v1 `views` and `serializers` packages are inspected
        THEN:  every former name is listed in the package's `__all__`
        AND:   every name in `__all__` resolves on the package, so it
               lists no stale entry
        """
        check.equal(
            sorted(set(names) - set(module.__all__)), [], "names in __all__"
        )
        check.equal(
            [n for n in module.__all__ if not hasattr(module, n)],
            [],
            "__all__ resolves",
        )


########################################################################
########################################################################
#
class TestBankAccountViewSetActions:
    """`BankAccountViewSet` routes its actions from the composed mixins."""

    ####################################################################
    #
    def test_extra_actions_unchanged(self) -> None:
        """
        GIVEN: `BankAccountViewSet` composed from the import, funding and
               invitation action mixins
        WHEN:  DRF collects its extra actions
        THEN:  exactly the nine bank-account actions are routed
        AND:   each keeps its `url_path` and HTTP methods
        """
        actions = {
            a.__name__: (a.url_path, set(a.mapping))
            for a in BankAccountViewSet.get_extra_actions()
        }
        assert actions == BANK_ACCOUNT_ACTIONS

    ####################################################################
    #
    @pytest.mark.parametrize(
        "mixin",
        [
            BankAccountImportActions,
            BankAccountFundingActions,
            BankAccountInvitationActions,
        ],
    )
    def test_mixins_in_mro(self, mixin: type) -> None:
        """
        GIVEN: a bank-account action mixin
        WHEN:  `BankAccountViewSet`'s MRO is resolved
        THEN:  the mixin precedes `ModelViewSet`, so its actions are
               discovered while the viewset's own class attributes win
        """
        mro = BankAccountViewSet.__mro__
        model_viewset = next(c for c in mro if c.__name__ == "ModelViewSet")
        assert mro.index(mixin) < mro.index(model_viewset)

    ####################################################################
    #
    @pytest.mark.parametrize("action_name", INVITATION_ACTIONS)
    def test_invitation_actions_require_interactive_auth(
        self, action_name: str
    ) -> None:
        """
        GIVEN: an owner-facing invitation action on `BankAccountViewSet`
        WHEN:  its routed `permission_classes` are read
        THEN:  they include `RequiresInteractiveAuth`, so machine
               credentials cannot send, list or cancel invitations
        """
        action = next(
            a
            for a in BankAccountViewSet.get_extra_actions()
            if a.__name__ == action_name
        )
        assert RequiresInteractiveAuth in action.kwargs["permission_classes"]
