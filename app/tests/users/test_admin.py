"""Tests for the User admin interface."""

# system imports
#

# 3rd party imports
#
import pytest
from django.test import Client
from django.urls import reverse

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

    def test_add(self, admin_client: Client) -> None:
        """
        GIVEN: an admin-authenticated client
        WHEN:  the add-user page is fetched (GET) and then a new user is
               submitted (POST) with valid credentials
        THEN:  the GET returns 200, the POST redirects (302), and the new user
               exists in the database
        """
        url = reverse("admin:users_user_add")
        response = admin_client.get(url)
        assert response.status_code == 200

        response = admin_client.post(
            url,
            data={
                "username": "test",
                "password1": "My_R@ndom-P@ssw0rd",
                "password2": "My_R@ndom-P@ssw0rd",
            },
        )
        assert response.status_code == 302
        assert User.objects.filter(username="test").exists()

    def test_view_user(self, admin_client: Client) -> None:
        """
        GIVEN: an admin-authenticated client and the built-in admin user
        WHEN:  the change page for that user is requested
        THEN:  a 200 response is returned
        """
        user = User.objects.get(username="admin")
        url = reverse("admin:users_user_change", kwargs={"object_id": user.pk})
        response = admin_client.get(url)
        assert response.status_code == 200
