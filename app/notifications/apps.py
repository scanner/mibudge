#!/usr/bin/env python
#
"""AppConfig for the notifications app."""

# system imports
#
import logging
from urllib.parse import urlparse

# 3rd party imports
#
from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
def _sync_site(sender: object, **kwargs: object) -> None:
    """Sync the django.contrib.sites Site row from SITE_URL/SITE_NAME settings.

    Runs after every migration so the Site record stays in sync with the
    environment without requiring a manual admin edit.  The django.contrib.sites
    migration creates a Site with domain 'example.com' on a fresh checkout,
    which breaks allauth password-reset links.  This hook self-corrects that
    on every 'make migrate' run -- if the domain already matches SITE_URL the
    update_or_create is a no-op.

    NOTE: Site is imported here rather than at module level because apps.py is
    loaded before the app registry is fully populated.  Importing a model class
    at module level in apps.py raises AppRegistryNotReady; deferring the import
    to inside the function avoids that -- by the time post_migrate fires, the
    registry is ready.
    """
    from django.contrib.sites.models import Site

    url = settings.SITE_URL
    name = settings.SITE_NAME
    netloc = urlparse(url).netloc or "localhost"
    site, created = Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={"domain": netloc, "name": name},
    )
    action = "created" if created else "updated"
    logger.debug("_sync_site: site %s %s (domain=%s)", site.id, action, netloc)


########################################################################
########################################################################
#
class NotificationsConfig(AppConfig):
    name = "notifications"

    ####################################################################
    #
    def ready(self) -> None:
        post_migrate.connect(_sync_site, sender=self)
