"""PostgreSQL backend that guarantees the `platform` schema exists (doc 04 §1).

Django keeps its tables in `platform`; Phoenix owns `rt`. Creating the schema on connection
setup means migrations, the test database and fresh environments all land in the right place.
"""

from django.db.backends.postgresql import base

SCHEMA = "platform"


class DatabaseWrapper(base.DatabaseWrapper):
    def init_connection_state(self) -> None:
        super().init_connection_state()
        # Skip maintenance connections (e.g. to the "postgres" database for CREATE/DROP DATABASE).
        if self.connection.info.dbname != self.settings_dict["NAME"]:
            return
        with self.connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
