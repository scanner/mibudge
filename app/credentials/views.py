#!/usr/bin/env python
#
"""
Server-rendered views for the OAuth2 authorization flow.

IMPORTANT -- why this flow has its own login page:

Everything else in mibudge authenticates without a Django session.  The
SPA logs in at /app/login/ and holds a JWT; API-key clients hit the REST
endpoints directly and never see a login page at all.  DOT's
AuthorizationView, however, is a LoginRequiredMixin: it needs
``request.user`` populated from a *session* before it can ask the user
to consent.  Pointing it at the SPA login would deadlock -- the SPA
authenticates the user and hands back a JWT, no session cookie is set,
and the authorize view bounces the user straight back to the login page.

So the OAuth2 flow gets its own server-rendered login at /o/login/.  It
takes the same email + password as the SPA, and the session it creates
exists only to carry the user through the consent screen.  This is also
the right shape for the traffic: a user arriving at /o/authorize/ came
from a 3rd-party app, not from a mibudge tab, so there is usually no
session or SPA state to reuse regardless.  See docs/authentication.md.
"""

# system imports
import hashlib
import logging

# 3rd party imports
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.forms import Form
from django.http import HttpRequest, HttpResponse
from django.urls import reverse_lazy
from oauth2_provider.views import AuthorizationView

# Project imports
from credentials.forms import OAuth2LoginForm
from credentials.models import Application

logger = logging.getLogger("credentials.views")

# Cache-key prefix for the failed-login counter.
_LOGIN_FAILURE_PREFIX = "oauth2-login-failures"


####################################################################
#
def _failure_cache_key(email: str) -> str:
    """Return the failed-attempt cache key for an email address.

    The address is hashed so login identifiers are not written to the
    cache in the clear.

    Args:
        email: The submitted email address.

    Returns:
        A cache key string.
    """
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"{_LOGIN_FAILURE_PREFIX}:{digest}"


########################################################################
########################################################################
#
class OAuth2LoginView(LoginView):
    """Email + password login that gates the consent screen.

    Throttling is keyed on the *submitted email address* rather than the
    client IP.  Behind a proxy every request shares one REMOTE_ADDR, so
    an IP-keyed counter would collapse into a single global limit that
    one attacker could trip to lock every user out.  Keying on the
    address means a determined attacker can stall one account's OAuth2
    login for the window (the SPA login, the primary path, is
    unaffected), which is the smaller failure.

    NOTE: the cache is configured with IGNORE_EXCEPTIONS, so if Redis is
    down this throttle fails open rather than locking users out of a
    working service.
    """

    template_name = "credentials/oauth2_login.html"
    authentication_form = OAuth2LoginForm
    redirect_authenticated_user = True

    ####################################################################
    #
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Reject the attempt when the address is over its failure limit.

        Args:
            request: The incoming request.

        Returns:
            The rendered form with a throttle error and status 429 when
            the limit is exceeded, otherwise the normal login response.
        """
        email = request.POST.get("username", "")
        if email and self._is_throttled(email):
            logger.warning(
                "OAuth2 login throttled for %r after %d failed attempts.",
                email,
                settings.OAUTH2_LOGIN_MAX_ATTEMPTS,
            )
            form = self.get_form()
            form.errors.setdefault("__all__", form.error_class()).append(
                "Too many failed sign-in attempts. Please wait a few "
                "minutes and try again."
            )
            return self.render_to_response(
                self.get_context_data(form=form), status=429
            )
        return super().post(request, *args, **kwargs)

    ####################################################################
    #
    def form_valid(self, form: AuthenticationForm) -> HttpResponse:
        """Clear the failure counter and log the user in."""
        cache.delete(_failure_cache_key(form.cleaned_data["username"]))
        return super().form_valid(form)

    ####################################################################
    #
    def form_invalid(self, form: AuthenticationForm) -> HttpResponse:
        """Count the failed attempt, then re-render the form."""
        email = form.data.get("username", "")
        if email:
            self._record_failure(email)
        return super().form_invalid(form)

    ####################################################################
    #
    @staticmethod
    def _is_throttled(email: str) -> bool:
        """True if this address has exhausted its failed-attempt budget."""
        failures = cache.get(_failure_cache_key(email), 0)
        return bool(failures >= settings.OAUTH2_LOGIN_MAX_ATTEMPTS)

    ####################################################################
    #
    @staticmethod
    def _record_failure(email: str) -> None:
        """Increment the failed-attempt counter for an address.

        The window is a fixed expiry from the FIRST failure rather than a
        sliding one: cache.incr() cannot extend a TTL, and a sliding
        window would let a slow attacker hold the key alive forever.
        """
        key = _failure_cache_key(email)
        # add() only sets the key if absent, so the TTL is anchored to
        # the first failure in the window.
        if cache.add(key, 1, timeout=settings.OAUTH2_LOGIN_WINDOW_SECONDS):
            return
        try:
            cache.incr(key)
        except ValueError:
            # The key expired between add() and incr(); the next failure
            # starts a fresh window.
            pass


########################################################################
########################################################################
#
class OAuth2AuthorizationView(AuthorizationView):
    """DOT's consent view, pointed at the OAuth2 login page.

    LoginRequiredMixin would otherwise send an unauthenticated visitor to
    settings.LOGIN_URL -- the SPA -- which cannot produce the session
    this view requires.  See the module docstring.

    It also enforces app visibility.  DOT resolves the application from
    its client_id alone and never looks at our `visibility`/`status`
    fields, so on its own it would let any signed-in user authorize --
    and hand their whole financial history to -- anyone's private,
    unpublished app just by knowing the client_id.  Both entry points are
    guarded: the GET that renders the consent screen and the POST
    (`form_valid`) that mints the grant, so the check cannot be skipped by
    POSTing straight past the screen.
    """

    login_url = reverse_lazy("oauth2_provider:login")

    ####################################################################
    #
    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Guard the consent screen, then defer to DOT."""
        denial = self._deny_unauthorizable(request.GET.get("client_id"))
        if denial is not None:
            return denial
        return super().get(request, *args, **kwargs)

    ####################################################################
    #
    def form_valid(self, form: Form) -> HttpResponse:
        """Guard grant creation, then defer to DOT."""
        denial = self._deny_unauthorizable(form.cleaned_data.get("client_id"))
        if denial is not None:
            return denial
        return super().form_valid(form)

    ####################################################################
    #
    def _deny_unauthorizable(
        self, client_id: str | None
    ) -> HttpResponse | None:
        """Return a 403 consent-denied page if the app is off-limits.

        Returns None -- let DOT proceed and render its own errors -- when
        the app is authorizable by the requesting user OR the client_id
        is absent/unknown (an unknown client is DOT's error to report,
        not ours, and answering it here would leak nothing but does not
        belong to this gate).
        """
        if not client_id:
            return None
        application = Application.objects.filter(client_id=client_id).first()
        if application is None or application.is_authorizable_by(
            self.request.user
        ):
            return None
        # Reuse the consent template's error branch so the denial is
        # styled like the rest of the flow.  A dict is enough: the
        # template reads only `error.error` and `error.description`.
        return self.render_to_response(
            {
                "error": {
                    "error": "access_denied",
                    "description": (
                        "This application is not available for authorization."
                    ),
                }
            },
            status=403,
        )
