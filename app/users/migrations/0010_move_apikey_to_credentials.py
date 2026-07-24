# APIKey moved to the new `credentials` app so all machine credentials
# (API keys, OAuth2 apps/tokens, the future scope model) live together.
#
# State-only: the model leaves this app's migration state without
# touching the database.  credentials/0001_initial recreates it in
# state (pointing at the existing table) and then renames the table --
# it depends on this migration so the two APIKey model states never
# coexist.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_apikey_expiry_notified_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="APIKey"),
            ],
            database_operations=[],
        ),
    ]
