from django.urls import path

from users.email_change import (
    EMAIL_CHANGE_CONFIRM_URL_NAME,
    EMAIL_CHANGE_REVOKE_URL_NAME,
)
from users.views import (
    email_change_confirm_view,
    email_change_revoke_view,
    user_detail_view,
    user_redirect_view,
    user_update_view,
)

app_name = "users"
urlpatterns = [
    path("~redirect/", view=user_redirect_view, name="redirect"),
    path("~update/", view=user_update_view, name="update"),
    path("<str:username>/", view=user_detail_view, name="detail"),
    # Email-change browser fallback views.  Native apps intercept these
    # URLs via Universal Links / App Links and call the REST API instead;
    # see users/email_change.py for the full dual-path design note.
    path(
        "email-change/<str:token>/confirm/",
        view=email_change_confirm_view,
        name=EMAIL_CHANGE_CONFIRM_URL_NAME,
    ),
    path(
        "email-change/<str:token>/revoke/",
        view=email_change_revoke_view,
        name=EMAIL_CHANGE_REVOKE_URL_NAME,
    ),
]
