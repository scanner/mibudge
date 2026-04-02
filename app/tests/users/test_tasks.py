import pytest
from celery.result import EagerResult
from django.contrib.auth import get_user_model

from tests.users.factories import UserFactory
from users.tasks import get_users_count

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_user_count(settings):
    """A basic test to execute the get_users_count Celery task."""
    UserFactory.create_batch(3)
    num_user_objects = User.objects.count()
    settings.CELERY_TASK_ALWAYS_EAGER = True
    task_result = get_users_count.delay()
    assert isinstance(task_result, EagerResult)
    assert task_result.result == num_user_objects
