#!/usr/bin/env python
#
"""
Acceptance page view for admin-initiated user invitations.

Registered in moneypools/invitation_urls.py under the ``invitations``
namespace at ``/invitations/user/{token}/``.

TODO: implement the full GET/POST acceptance flow (see task-mibudge-user-invitations).
"""

from django.http import HttpRequest, HttpResponse


def user_invitation_view(request: HttpRequest, token: str) -> HttpResponse:
    """Placeholder -- full implementation pending."""
    return HttpResponse(status=200)
