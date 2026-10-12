-- Per-service database roles (ADR-019, doc 04 §1). Run as a superuser; idempotent.
--
--   psql -v ON_ERROR_STOP=1 -v db=luxrocket \
--        -v platform_user=lr_platform -v realtime_user=lr_realtime -v portal_role=lr_portal \
--        -f infra/postgres/roles.sql
--
-- Login passwords, when given, are read from the environment (never the command line):
-- PLATFORM_DB_PASSWORD and REALTIME_DB_PASSWORD.
--
-- platform_user  Django: owns schema `platform`; reads (never writes) schema `rt`.
-- realtime_user  Phoenix: owns schema `rt` (and Ecto's public.schema_migrations); cannot see
--                `platform` at all.
-- portal_role    NOLOGIN; the operator portal's request transactions SET ROLE to it and run
--                under row-level security (grants and policies: luxrocket/core/tenancy.py).
--
-- A single-user development database passes the same name for platform_user and realtime_user;
-- only the portal role and its membership are then set up.

SELECT set_config('lr.db', :'db', false),
       set_config('lr.platform', :'platform_user', false),
       set_config('lr.realtime', :'realtime_user', false),
       set_config('lr.portal', :'portal_role', false);

DO $$
DECLARE
  db       text := current_setting('lr.db');
  platform text := current_setting('lr.platform');
  realtime text := current_setting('lr.realtime');
  portal   text := current_setting('lr.portal');
  split    boolean := platform <> realtime;
  obj      record;
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = platform) THEN
    EXECUTE format('CREATE ROLE %I LOGIN', platform);
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = realtime) THEN
    EXECUTE format('CREATE ROLE %I LOGIN', realtime);
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = portal) THEN
    EXECUTE format('CREATE ROLE %I NOLOGIN', portal);
  END IF;
  EXECUTE format('GRANT %I TO %I', portal, platform);
  EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I, %I', db, platform, realtime);

  EXECUTE format('CREATE SCHEMA IF NOT EXISTS platform AUTHORIZATION %I', platform);
  EXECUTE format('CREATE SCHEMA IF NOT EXISTS rt AUTHORIZATION %I', realtime);
  EXECUTE format('ALTER SCHEMA platform OWNER TO %I', platform);
  EXECUTE format('ALTER SCHEMA rt OWNER TO %I', realtime);

  IF NOT split THEN
    RETURN;
  END IF;

  -- Adopt objects created by an earlier single-user stack.
  FOR obj IN
    SELECT n.nspname, c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname IN ('platform', 'rt') AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
       -- Owned sequences (serial 'a', identity 'i') follow their table.
       AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a', 'i'))
  LOOP
    EXECUTE format(
      'ALTER %s %I.%I OWNER TO %I',
      CASE obj.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW'
                       WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,
      obj.nspname, obj.relname,
      CASE obj.nspname WHEN 'platform' THEN platform ELSE realtime END);
  END LOOP;

  -- public holds only Ecto's migration ledger.
  EXECUTE 'REVOKE CREATE ON SCHEMA public FROM PUBLIC';
  EXECUTE format('GRANT USAGE, CREATE ON SCHEMA public TO %I', realtime);
  IF to_regclass('public.schema_migrations') IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.schema_migrations OWNER TO %I', realtime);
  END IF;

  -- Each service sees only its own schema; the platform reads round facts.
  EXECUTE 'REVOKE ALL ON SCHEMA platform FROM PUBLIC';
  EXECUTE 'REVOKE ALL ON SCHEMA rt FROM PUBLIC';
  EXECUTE format('GRANT USAGE ON SCHEMA rt TO %I', platform);
  EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA rt TO %I', platform);
  EXECUTE format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA rt GRANT SELECT ON TABLES TO %I',
    realtime, platform);
  -- ...except encrypted seed material (same rule as the Phoenix migration
  -- 20261012100000_seed_secrets_column_grants, which covers databases migrated after this).
  IF to_regclass('rt.seed_checkpoint') IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON rt.seed_checkpoint FROM %I', platform);
  END IF;
  IF to_regclass('rt.seed_chain') IS NOT NULL THEN
    EXECUTE format('REVOKE ALL ON rt.seed_chain FROM %I', platform);
    EXECUTE format(
      'GRANT SELECT (chain_id, stream_id, length, terminal_hash, salt, salt_source, '
      'checkpoint_every, status, inserted_at, drand_chain_hash, drand_round, drand_signature, '
      'committed_at, activated_at, retired_at) ON rt.seed_chain TO %I', platform);
  END IF;
END $$;

\getenv platform_password PLATFORM_DB_PASSWORD
\getenv realtime_password REALTIME_DB_PASSWORD
\if :{?platform_password}
ALTER ROLE :"platform_user" PASSWORD :'platform_password';
\endif
\if :{?realtime_password}
ALTER ROLE :"realtime_user" PASSWORD :'realtime_password';
\endif
