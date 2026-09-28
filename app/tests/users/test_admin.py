"""Tests for the User admin interface."""

# system imports
#

# 3rd party imports
#
import pytest
import pytest_check as check
from django.test import Client
from django.urls import reverse
from faker import Faker

# app imports
#
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserAdmin:
    """Tests for the User model's Django admin views."""

    @pytest.mark.parametrize(
        "query_params",
        [
            pytest.param({}, id="no-filter"),
            pytest.param({"q": "test"}, id="search"),
        ],
    )
    def test_changelist(
        self, admin_client: Client, query_params: dict[str, str]
    ) -> None:
        """
        GIVEN: an admin-authenticated client
        WHEN:  the user changelist is requested, with and without a search query
        THEN:  a 200 response is returned in both cases
        """
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url, data=query_params)
        assert response.status_code == 200

    def test_add(self, admin_client: Client, faker: Faker) -> None:
        """
        GIVEN: an admin-authenticated client
        WHEN:  the add-user page is fetched (GET) and then a new user is
               submitted (POST) with valid credentials
        THEN:  the GET returns 200, the POST redirects (302), and the new user
               exists in the database
        """
        url = reverse("admin:users_user_add")
        username = faker.unique.user_name()
        password = faker.password(length=20)

        form = admin_client.get(url)
        response = admin_client.post(
            url,
            data={
                "username": username,
                "email": faker.unique.email(),
                "password1": password,
                "password2": password,
            },
        )

        check.equal(form.status_code, 200, "add page renders")
        check.equal(response.status_code, 302, "submit redirects")
        check.is_true(
            User.objects.filter(username=username).exists(), "user created"
        )

    def test_view_user(self, admin_client: Client, admin_user: User) -> None:
        """
        GIVEN: an admin-authenticated client and the built-in admin user
        WHEN:  the change page for that user is requested
        THEN:  a 200 response is returned
        """
        url = reverse(
            "admin:users_user_change", kwargs={"object_id": admin_user.pk}
        )
        response = admin_client.get(url)
        assert response.status_code == 200
