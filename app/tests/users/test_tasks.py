"""Tests for users Celery tasks."""

# system imports
#

# 3rd party imports
#
import pytest
from celery.result import EagerResult
from django.conf import LazySettings
from django.contrib.auth import get_user_model

# app imports
#
from tests.users.factories import UserFactory
from users.tasks import get_users_count

pytestmark = pytest.mark.django_db

User = get_user_model()


########################################################################
########################################################################
#
class TestGetUsersCountTask:
    """Tests for the get_users_count Celery task."""

    def test_returns_correct_count(self, settings: LazySettings) -> None:
        """
        GIVEN: three users created via the factory
        WHEN:  the get_users_count task is executed eagerly
        THEN:  the task returns an EagerResult whose value matches the
               database count of User objects
        """
        UserFactory.create_batch(3)
        num_user_objects = User.objects.count()
        settings.CELERY_TASK_ALWAYS_EAGER = True

        task_result = get_users_count.delay()

        assert isinstance(task_result, EagerResult)
        assert task_result.result == num_user_objects
