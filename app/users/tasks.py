#!/usr/bin/env python
#
"""Celery tasks for the users app."""

# system imports
import logging

# 3rd party imports
from django.contrib.auth import get_user_model

# Project imports
from config import celery_app

logger = logging.getLogger("users.tasks")

User = get_user_model()


########################################################################
########################################################################
#
@celery_app.task()
def get_users_count():
    """A pointless Celery task to demonstrate usage."""
    return User.objects.count()
