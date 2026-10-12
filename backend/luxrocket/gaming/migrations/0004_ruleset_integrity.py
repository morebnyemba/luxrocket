"""Approved rulesets are immutable (only APPROVED -> RETIRED), and the default binding exists."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION platform.ruleset_immutable() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'DRAFT' THEN
      RAISE EXCEPTION 'ruleset % is % and cannot be deleted', OLD.code, OLD.status;
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status <> 'DRAFT' AND (
       NEW.code, NEW.formula, NEW.house_edge_bp, NEW.max_multiplier_x10000, NEW.certification_ref
     ) IS DISTINCT FROM (
       OLD.code, OLD.formula, OLD.house_edge_bp, OLD.max_multiplier_x10000, OLD.certification_ref
     ) THEN
    RAISE EXCEPTION 'ruleset % is % and its parameters are immutable', OLD.code, OLD.status;
  END IF;
  IF OLD.status = 'RETIRED' AND NEW.status <> 'RETIRED' THEN
    RAISE EXCEPTION 'ruleset % is retired', OLD.code;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER ruleset_immutable
  BEFORE UPDATE OR DELETE ON platform.gaming_gameruleset
  FOR EACH ROW EXECUTE FUNCTION platform.ruleset_immutable();
"""

REVERSE = """
DROP TRIGGER IF EXISTS ruleset_immutable ON platform.gaming_gameruleset;
DROP FUNCTION IF EXISTS platform.ruleset_immutable();
"""


def seed(apps, schema_editor):
    GameRuleset = apps.get_model("gaming", "GameRuleset")
    StreamConfig = apps.get_model("gaming", "StreamConfig")
    default, _ = GameRuleset.objects.get_or_create(
        code="LR-STD-97",
        defaults={
            "house_edge_bp": 300,
            "max_multiplier_x10000": 100_000_000,
            "status": "APPROVED",
            # Honest placeholder: the sandbox default has not been through a test lab yet.
            "certification_ref": "NOT CERTIFIED (sandbox default; certify before real money)",
            "notes": "Platform default: 97% RTP, 10,000x cap (doc 07).",
            "created_by": "migration",
            "approved_by": "migration",
        },
    )
    StreamConfig.objects.get_or_create(stream_slug="global", defaults={"ruleset": default})


class Migration(migrations.Migration):
    dependencies = [("gaming", "0003_rulesets")]
    operations = [
        migrations.RunSQL(SQL, REVERSE),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
