#!/usr/bin/env python
#
"""
Django template views for the bank-account co-ownership invitation flow.

Served at /invitations/account/{token}/ -- outside the SPA so that
unauthenticated invitees (brand-new users) can access the page without
going through the JWT auth bootstrap.

The DRF endpoints at /api/v1/invitations/{token}/... mirror this logic
for native-app clients.  Both paths call the same service functions.
"""

# system imports
#
import logging

# 3rd party imports
#
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

# Project imports
#
from moneypools.models import BankAccountInvitation
from moneypools.service import invitation as invitation_svc

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
def account_invitation_view(request: HttpRequest, token: str) -> HttpResponse:
    """Render the co-ownership invitation acceptance page.

    GET: show the invitation details (or an error if the token is
         invalid/expired/terminal).
    POST action=accept: accept the invitation.
    POST action=decline: decline the invitation.

    After a POST the same template is re-rendered with a 'result'
    context key ('accepted', 'declined', or an error string) so the URL
    stays stable and no redirect is needed.
    """
    # Look up the invitation.  An unknown token shows a generic error.
    try:
        invitation = BankAccountInvitation.objects.select_related(
            "bank_account",
            "bank_account__bank",
            "invited_by",
            "invitee_user",
        ).get(token=token)
    except BankAccountInvitation.DoesNotExist:
        return render(
            request,
            "pages/invitations/account_invitation.html",
            {"error": "not_found"},
        )

    # Collect all pending invitations for the same email address so the
    # page can list them all (multi-invitation support).
    all_pending = list(
        BankAccountInvitation.pending_for_email(invitation.invitee_email)
    )

    is_new_user = (
        invitation.invitee_user is not None
        and not invitation.invitee_user.has_usable_password()
    )

    base_ctx: dict = {
        "invitation": invitation,
        "all_pending": all_pending,
        "is_new_user": is_new_user,
    }

    if request.method == "GET":
        # Surface terminal / expired states on GET without consuming the token.
        if invitation.is_terminal:
            return render(
                request,
                "pages/invitations/account_invitation.html",
                {**base_ctx, "error": invitation.status},
            )
        if invitation.is_expired:
            return render(
                request,
                "pages/invitations/account_invitation.html",
                {**base_ctx, "error": "expired"},
            )
        return render(
            request,
            "pages/invitations/account_invitation.html",
            base_ctx,
        )

    # POST path
    action = request.POST.get("action")

    match action:
        case "accept":
            try:
                invitation_svc.accept_invitation(token, request=request)
                result = "accepted"
            except invitation_svc.TokenExpiredError:
                result = "expired"
            except invitation_svc.TokenAlreadyCancelledError:
                result = "cancelled"
            except (
                invitation_svc.TokenAlreadyAcceptedError,
                invitation_svc.TokenAlreadyDeclinedError,
                invitation_svc.TokenNotFoundError,
            ):
                result = "already_actioned"

        case "decline":
            try:
                invitation_svc.decline_invitation(token)
                result = "declined"
            except invitation_svc.TokenExpiredError:
                result = "expired"
            except invitation_svc.TokenAlreadyCancelledError:
                result = "cancelled"
            except (
                invitation_svc.TokenAlreadyAcceptedError,
                invitation_svc.TokenAlreadyDeclinedError,
                invitation_svc.TokenNotFoundError,
            ):
                result = "already_actioned"

        case _:
            result = "bad_request"

    # Re-fetch so the template sees the updated status.
    invitation.refresh_from_db()
    return render(
        request,
        "pages/invitations/account_invitation.html",
        {**base_ctx, "invitation": invitation, "result": result},
    )
