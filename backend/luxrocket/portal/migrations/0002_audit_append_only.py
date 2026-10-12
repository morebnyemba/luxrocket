"""The audit log is append-only at the database level (doc 15 §4, T-13)."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION platform.audit_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit events are append-only';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER audit_no_update_delete
  BEFORE UPDATE OR DELETE ON platform.portal_auditevent
  FOR EACH ROW EXECUTE FUNCTION platform.audit_immutable();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_no_update_delete ON platform.portal_auditevent;
DROP FUNCTION IF EXISTS platform.audit_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("portal", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
