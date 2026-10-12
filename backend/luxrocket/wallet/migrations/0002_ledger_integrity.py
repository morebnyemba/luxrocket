"""Ledger integrity enforced by the database, not just the application (FR-034, T-13).

1. UPDATE and DELETE on ledger entries are rejected.
2. Every journal must sum to zero, checked at commit (deferred constraint trigger).
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION platform.ledger_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'ledger entries are append-only';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_no_update_delete
  BEFORE UPDATE OR DELETE ON platform.wallet_ledgerentry
  FOR EACH ROW EXECUTE FUNCTION platform.ledger_immutable();

CREATE OR REPLACE FUNCTION platform.ledger_journal_balanced() RETURNS trigger AS $$
DECLARE total bigint;
BEGIN
  SELECT COALESCE(SUM(amount_minor), 0) INTO total
    FROM platform.wallet_ledgerentry WHERE journal_id = NEW.journal_id;
  IF total <> 0 THEN
    RAISE EXCEPTION 'ledger journal % is unbalanced (%)', NEW.journal_id, total;
  END IF;
  RETURN NULL;
END $$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ledger_balanced
  AFTER INSERT ON platform.wallet_ledgerentry
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION platform.ledger_journal_balanced();
"""

REVERSE = """
DROP TRIGGER IF EXISTS ledger_balanced ON platform.wallet_ledgerentry;
DROP TRIGGER IF EXISTS ledger_no_update_delete ON platform.wallet_ledgerentry;
DROP FUNCTION IF EXISTS platform.ledger_journal_balanced();
DROP FUNCTION IF EXISTS platform.ledger_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("wallet", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
