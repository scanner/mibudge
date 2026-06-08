from django.urls import path

from .invitation_views import account_invitation_view

app_name = "invitations"

urlpatterns = [
    path(
        "account/<str:token>/",
        account_invitation_view,
        name="account-invitation",
    ),
]
