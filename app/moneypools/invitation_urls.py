from django.urls import path

from users.invitation_views import user_invitation_view

from .invitation_views import account_invitation_view

app_name = "invitations"

urlpatterns = [
    path(
        "account/<str:token>/",
        account_invitation_view,
        name="account-invitation",
    ),
    path(
        "user/<str:token>/",
        user_invitation_view,
        name="user-invitation",
    ),
]
