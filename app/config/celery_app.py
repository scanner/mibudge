"""Celery application configuration and managed periodic task registry.

Periodic tasks defined in MANAGED_PERIODIC_TASKS are synced to the
django_celery_beat database tables when celery beat starts (via the
beat_init signal). Admin-created tasks are left untouched -- only tasks
whose names start with MANAGED_PREFIX are added, updated, or removed
by the sync.
"""

import json
import logging
import os

from celery import Celery
from celery.signals import beat_init

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mibudge")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

logger = logging.getLogger("config.celery_app")

# Managed tasks use this prefix so sync_periodic_tasks() can distinguish
# them from tasks created manually via the admin.
#
MANAGED_PREFIX = "[managed] "

# Registry of periodic tasks managed in code. Each key is a human-readable
# name (the prefix is prepended automatically). Values are dicts with:
#
#   task     - dotted path to the celery task
#   schedule - a dict accepted by IntervalSchedule or CrontabSchedule:
#              {"every": N, "period": "seconds"|"minutes"|"hours"|"days"}
#              {"crontab": {"minute": "0", "hour": "3", ...}}
#   args     - (optional) JSON-serializable list of positional args
#   kwargs   - (optional) JSON-serializable dict of keyword args
#   enabled  - (optional) bool, default True
#
# Example:
#
#   MANAGED_PERIODIC_TASKS = {
#       "Fund budgets daily": {
#           "task": "moneypools.tasks.fund_budgets",
#           "schedule": {"crontab": {"minute": "0", "hour": "3"}},
#       },
#   }
#
MANAGED_PERIODIC_TASKS: dict = {}


########################################################################
########################################################################
#
@beat_init.connect
def _on_beat_init(sender, **kwargs):
    """Sync managed periodic tasks when celery beat starts."""
    sync_periodic_tasks()


########################################################################
########################################################################
#
def sync_periodic_tasks() -> None:
    """Reconcile MANAGED_PERIODIC_TASKS with django_celery_beat models.

    - Creates missing managed tasks.
    - Updates existing managed tasks if their definition changed.
    - Deletes managed tasks that are no longer in the registry.
    - Never touches tasks without the MANAGED_PREFIX.
    """
    # Imported here because Django must be fully initialized first.
    #
    from django_celery_beat.models import (
        CrontabSchedule,
        IntervalSchedule,
        PeriodicTask,
    )

    managed_names = {
        f"{MANAGED_PREFIX}{name}" for name in MANAGED_PERIODIC_TASKS
    }

    # Remove stale managed tasks.
    #
    stale = PeriodicTask.objects.filter(
        name__startswith=MANAGED_PREFIX
    ).exclude(name__in=managed_names)
    if stale.exists():
        logger.info(
            "Removing stale managed periodic tasks: %s",
            list(stale.values_list("name", flat=True)),
        )
        stale.delete()

    # Create or update each managed task.
    #
    for name, defn in MANAGED_PERIODIC_TASKS.items():
        full_name = f"{MANAGED_PREFIX}{name}"
        schedule_conf = defn["schedule"]

        # Build the schedule object.
        #
        interval = None
        crontab = None

        if "crontab" in schedule_conf:
            crontab, _ = CrontabSchedule.objects.get_or_create(
                **schedule_conf["crontab"]
            )
        else:
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=schedule_conf["every"],
                period=schedule_conf["period"],
            )

        defaults = {
            "task": defn["task"],
            "interval": interval,
            "crontab": crontab,
            "args": json.dumps(defn.get("args", [])),
            "kwargs": json.dumps(defn.get("kwargs", {})),
            "enabled": defn.get("enabled", True),
        }

        task, created = PeriodicTask.objects.update_or_create(
            name=full_name, defaults=defaults
        )
        if created:
            logger.info("Created managed periodic task: %s", full_name)
        else:
            logger.debug("Updated managed periodic task: %s", full_name)
