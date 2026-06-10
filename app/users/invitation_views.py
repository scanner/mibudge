#!/usr/bin/env python
#
"""
Acceptance page view for admin-initiated user invitations.

Registered in moneypools/invitation_urls.py under the ``invitations``
namespace at ``/invitations/user/{token}/``.

GET: render the invitation details, or an error if the token is
     invalid/expired/terminal.
POST action=accept: accept the invitation; re-render with a result
     context key so the URL stays stable and no redirect is needed.
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
import users.invitation as invitation_svc
from users.models import UserInvitation

logger = logging.getLogger(__name__)

_TEMPLATE = "pages/invitations/user_invitation.html"


########################################################################
########################################################################
#
def user_invitation_view(request: HttpRequest, token: str) -> HttpResponse:
    """Render the user invitation acceptance page.

    GET: show the invitation details (or an error if the token is
         invalid/expired/terminal).
    POST action=accept: accept the invitation.

    After a POST the same template is re-rendered with a 'result'
    context key ('accepted' or an error string) so the URL stays
    stable and no redirect is needed.
    """
    try:
        invitation = UserInvitation.objects.select_related(
            "invited_by",
            "invitee_user",
        ).get(token=token)
    except UserInvitation.DoesNotExist:
        return render(request, _TEMPLATE, {"error": "not_found"})

    base_ctx: dict = {"invitation": invitation}

    if request.method == "GET":
        if invitation.is_terminal:
            return render(
                request, _TEMPLATE, {**base_ctx, "error": invitation.status}
            )
        if invitation.is_expired:
            return render(request, _TEMPLATE, {**base_ctx, "error": "expired"})
        return render(request, _TEMPLATE, base_ctx)

    # POST path -- only supported action is "accept"
    action = request.POST.get("action")

    match action:
        case "accept":
            try:
                invitation_svc.accept_user_invitation(token, request=request)
                result = "accepted"
            except invitation_svc.TokenExpiredError:
                result = "expired"
            except invitation_svc.TokenAlreadyCancelledError:
                result = "cancelled"
            except (
                invitation_svc.TokenAlreadyAcceptedError,
                invitation_svc.TokenNotFoundError,
            ):
                result = "already_actioned"
        case _:
            result = "bad_request"

    invitation.refresh_from_db()
    return render(
        request,
        _TEMPLATE,
        {**base_ctx, "invitation": invitation, "result": result},
    )
