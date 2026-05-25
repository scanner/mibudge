#!/usr/bin/env python
#
"""
Email notification channel.

Template convention
-------------------
Templates live under templates/notifications/<app>/<kind>/ where <app>
and <kind> come from splitting the dotted kind string on the first dot.
For a kind like "moneypools.funding_complete" the template directory is
"notifications/moneypools/funding_complete/".

Each template file name encodes the locale::

    email_subject.<locale>.txt      -- subject line (single line)
    email_body.<locale>.txt         -- plain-text body
    email_body.<locale>.html        -- HTML body

Locale values are BCP 47 tags matching Django's LANGUAGE_CODE convention
(e.g. 'en-us', 'fr-ca', 'zh-hans'), so filenames look like
'email_body.en-us.html'.

For standalone (CRITICAL) sends these templates are used directly.
For digest batches a shared digest wrapper template is used, and each
notification's HTML/text body is rendered as an inline section.

Locale fallback
---------------
If the user's locale template does not exist, the loader falls back to
NOTIFICATIONS_DEFAULT_LOCALE.  Supporting a new language requires only
new template files; no code changes are needed.
"""

# system imports
#
import logging
from urllib.parse import urlparse

# 3rd party imports
#
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template import TemplateDoesNotExist
from django.template.loader import get_template, render_to_string
from django.utils import timezone

# Project imports
#
from notifications.channels.base import BaseChannel
from notifications.models import (
    Notification,
    NotificationLog,
    NotificationStatus,
)
from notifications.senders import get_sender

logger = logging.getLogger(__name__)

# Local-time hours (inclusive start, exclusive end) for morning/evening
# digest windows.  Matches the window checked in tasks.flush_email_digests.
#
_MORNING_WINDOW = (7, 8)
_EVENING_WINDOW = (18, 19)


def _fallback_locale() -> str:
    return settings.NOTIFICATIONS_DEFAULT_LOCALE


########################################################################
########################################################################
#
def _site_context() -> dict[str, str]:
    """Return template context variables derived from SITE_URL.

    Injected into every outgoing notification email so templates can
    link back to the app and provide a support contact address.

    Returns:
        Dict with 'site_url' (trailing slash stripped) and
        'support_email' (support@<hostname>).
    """
    url = settings.SITE_URL.rstrip("/")
    hostname = urlparse(url).hostname or "localhost"
    return {"site_url": url, "support_email": f"support@{hostname}"}


########################################################################
########################################################################
#
def _kind_template_dir(kind: str) -> str:
    """
    Convert a dotted kind string to a template directory path.

    Args:
        kind: Dotted kind string, e.g. 'moneypools.funding_complete'.

    Returns:
        Template subdirectory, e.g. 'notifications/moneypools/funding_complete'.
    """
    return "notifications/" + kind.replace(".", "/")


########################################################################
########################################################################
#
def _template_path(kind: str, name: str, locale: str) -> str:
    """
    Build a full template path with locale.

    Args:
        kind: Dotted kind string.
        name: Base template name, e.g. 'email_subject'.
        locale: Locale tag, e.g. 'en_US'.

    Returns:
        Template path, e.g.
        'notifications/moneypools/funding_complete/email_subject.en_US.txt'.
    """
    return f"{_kind_template_dir(kind)}/{name}.{locale}.txt"


########################################################################
########################################################################
#
def _render_with_fallback(
    kind: str,
    name: str,
    locale: str,
    context: dict,
) -> str:
    """
    Render a template, falling back to en_US if the locale version is absent.

    Args:
        kind: Dotted kind string.
        name: Base template name (e.g. 'email_subject', 'email_body.txt').
        locale: Preferred locale.
        context: Template context dict.

    Returns:
        Rendered string.

    Raises:
        django.template.TemplateDoesNotExist: If neither the locale
            nor the en_US fallback template exists.
    """
    for candidate_locale in _locale_candidates(locale):
        path = _template_path(kind, name, candidate_locale)
        try:
            get_template(path)
            return render_to_string(path, context)
        except TemplateDoesNotExist:
            continue

    raise TemplateDoesNotExist(
        f"No template found for kind={kind!r} name={name!r} "
        f"locale={locale!r} (tried {_locale_candidates(locale)})"
    )


########################################################################
########################################################################
#
def _render_html_with_fallback(
    kind: str,
    locale: str,
    context: dict,
) -> str:
    """
    Render the HTML body template, falling back to en_US.

    Uses a .html extension rather than .txt.

    Args:
        kind: Dotted kind string.
        locale: Preferred locale.
        context: Template context dict.

    Returns:
        Rendered HTML string.
    """
    for candidate_locale in _locale_candidates(locale):
        path = f"{_kind_template_dir(kind)}/email_body.{candidate_locale}.html"
        try:
            get_template(path)
            return render_to_string(path, context)
        except TemplateDoesNotExist:
            continue

    raise TemplateDoesNotExist(
        f"No HTML body template found for kind={kind!r} locale={locale!r}"
    )


########################################################################
########################################################################
#
def _render_shared_template(
    name: str, ext: str, locale: str, context: dict
) -> str:
    """
    Render a shared (non-kind-specific) notification template with locale fallback.

    Used for the digest wrapper templates that live directly under
    templates/notifications/ rather than under a kind subdirectory.

    Args:
        name: Base template name, e.g. 'email_digest_subject'.
        ext: File extension without dot, e.g. 'txt' or 'html'.
        locale: Preferred BCP 47 locale.
        context: Template context dict.

    Returns:
        Rendered string.

    Raises:
        django.template.TemplateDoesNotExist: If no template is found.
    """
    for candidate_locale in _locale_candidates(locale):
        path = f"notifications/{name}.{candidate_locale}.{ext}"
        try:
            get_template(path)
            return render_to_string(path, context)
        except TemplateDoesNotExist:
            continue

    raise TemplateDoesNotExist(
        f"No shared template found for name={name!r} locale={locale!r}"
    )


########################################################################
########################################################################
#
def _locale_candidates(locale: str) -> list[str]:
    """
    Return locale strings to try in order.

    Args:
        locale: Preferred BCP 47 locale, e.g. 'fr-ca'.

    Returns:
        List of locales to try, ending with the configured default fallback.
    """
    fallback = _fallback_locale()
    if locale == fallback:
        return [fallback]
    return [locale, fallback]


########################################################################
########################################################################
#
class EmailChannel(BaseChannel):
    """Email notification channel using Django's mail framework (anymail)."""

    ####################################################################
    #
    def send(self, notification: "Notification") -> None:
        """
        Send a standalone email for a single notification.

        Used for CRITICAL priority notifications that bypass the digest
        queue.

        Args:
            notification: A Notification model instance.
        """
        self._dispatch([notification], digest=False)

    ####################################################################
    #
    def send_batch(self, notifications: list) -> None:
        """
        Send a digest email containing all notifications in the batch.

        Args:
            notifications: List of Notification model instances to batch.
        """
        if not notifications:
            return
        self._dispatch(notifications, digest=True)

    ####################################################################
    #
    def _dispatch(
        self,
        notifications: list,
        digest: bool,
    ) -> None:
        """
        Render templates and send email for a list of notifications.

        For a single non-digest notification, the kind-specific templates
        are used directly.  For digests (including a batch of one), the
        shared digest wrapper is used and each notification's body is
        rendered inline.

        Args:
            notifications: Non-empty list of Notification instances.
            digest: True when sending via the digest path (uses wrapper).
        """
        # Use the first notification's user and locale -- all items in a
        # digest batch belong to the same user.
        first = notifications[0]
        user = first.user
        locale = first.locale

        site_ctx = _site_context()

        # Build per-item context for digest rendering.
        items = []
        for n in notifications:
            ctx = dict(n.context)
            ctx["notification"] = n
            ctx.update(site_ctx)
            items.append(
                {
                    "notification": n,
                    "text_body": _render_with_fallback(
                        n.kind, "email_body", n.locale, ctx
                    ),
                    "html_body": _render_html_with_fallback(
                        n.kind, n.locale, ctx
                    ),
                }
            )

        if digest or len(notifications) > 1:
            digest_ctx = {
                "user": user,
                "items": items,
                "item_count": len(items),
                **site_ctx,
            }
            subject = _render_shared_template(
                "email_digest_subject", "txt", locale, digest_ctx
            ).strip()
            text_body = _render_shared_template(
                "email_digest_body", "txt", locale, digest_ctx
            )
            html_body = _render_shared_template(
                "email_digest_body", "html", locale, digest_ctx
            )
        else:
            n = notifications[0]
            ctx = dict(n.context)
            ctx["notification"] = n
            ctx.update(site_ctx)
            subject = _render_with_fallback(
                n.kind, "email_subject", locale, ctx
            ).strip()
            text_body = items[0]["text_body"]
            html_body = items[0]["html_body"]

        sender_config = get_sender(notifications[0].sender_id or None)
        connection = None
        if not settings.DEBUG and sender_config.smtp_user:
            connection = get_connection(
                backend=settings.EMAIL_BACKEND,
                host=settings.EMAIL_HOST,
                port=settings.EMAIL_PORT,
                username=sender_config.smtp_user,
                password=sender_config.smtp_password,
                use_tls=getattr(settings, "EMAIL_USE_TLS", True),
            )

        log_entry = NotificationLog.objects.create(
            user=user,
            channel="email",
        )

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=sender_config.from_email,
                to=[user.email],
                connection=connection,
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()

            now = timezone.now()
            log_entry.status = NotificationStatus.SENT
            log_entry.sent_at = now
            log_entry.save(update_fields=["status", "sent_at"])

            # Link all dispatched notifications to this log entry.
            Notification.objects.filter(
                id__in=[str(n.id) for n in notifications]
            ).update(log_entry=log_entry)

            logger.info(
                "Sent email notification(s) to %s: %d item(s), kinds=%s",
                user.email,
                len(notifications),
                [n.kind for n in notifications],
            )
        except Exception as exc:
            log_entry.status = NotificationStatus.FAILED
            log_entry.error_detail = str(exc)
            log_entry.save(update_fields=["status", "error_detail"])
            logger.error(
                "Failed to send email notification to %s: %r",
                user.email,
                exc,
            )
            raise
