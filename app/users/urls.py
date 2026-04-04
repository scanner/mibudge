from django.urls import path

from users.views import (
    spa_login_view,
    user_detail_view,
    user_redirect_view,
    user_update_view,
)

app_name = "users"
urlpatterns = [
    path("~redirect/", view=user_redirect_view, name="redirect"),
    path("~update/", view=user_update_view, name="update"),
    path("~spa-login/", view=spa_login_view, name="spa-login"),
    path("<str:username>/", view=user_detail_view, name="detail"),
]
