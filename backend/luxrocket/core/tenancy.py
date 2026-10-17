"""Tenant isolation in the database (ADR-019 §3): Postgres row-level security for the portal.

Operator-portal requests run their queries as the NOLOGIN role `PORTAL_DB_ROLE` (`SET LOCAL ROLE`
inside the request transaction) with `app.operator_id` set to the signed-in operator. That role
can only see the tables classified below, and on tenant tables only its own operator's rows, so
a query that forgets its `operator=` filter returns nothing foreign instead of leaking it.

This is defence in depth beneath the scoped queries and the cross-tenant route suite, not a
sandbox: code running in the request can still leave the scope deliberately via `unscoped()`
(used for the global audit hash chain), which is why every such call is explicit and greppable.

Every table in the platform schema must be classified here; `tests/test_tenancy.py` fails when a
new table is not, so adding a table forces a decision about portal access.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction

SCHEMA = "platform"
_OPERATOR = "NULLIF(current_setting('app.operator_id', true), '')::uuid"


@dataclass(frozen=True)
class Tenant:
    """A table whose rows belong to one operator. `owner` is the SQL that yields the row's
    operator id; `privileges` are granted on top of SELECT."""

    owner: str = "operator_id"
    privileges: tuple[str, ...] = ()


def _via(table: str, fk: str, key: str = "id", owner: str = "operator_id") -> str:
    """The owning operator of a child row, through its parent (identifiers are constants)."""
    return f"(SELECT p.{owner} FROM {SCHEMA}.{table} p WHERE p.{key} = {fk})"  # noqa: S608


TENANT: dict[str, Tenant] = {
    # The operator row itself: the portal edits only its wallet routing.
    "operators_operator": Tenant(
        owner="id",
        privileges=(
            "UPDATE (wallet_kind, wallet_base_url, wallet_debit_timeout_ms, "
            "wallet_conformance_passed_at)",
        ),
    ),
    "operators_operatorcredential": Tenant(privileges=("INSERT", "UPDATE")),
    "operators_idempotencyrecord": Tenant(),
    "operators_operatordomain": Tenant(),
    "operators_operatorcurrencylimit": Tenant(),
    "operators_operatorjurisdiction": Tenant(),
    "operators_webhookendpoint": Tenant(privileges=("INSERT", "UPDATE")),
    "operators_webhookdelivery": Tenant(privileges=("INSERT", "UPDATE")),
    "gaming_playerref": Tenant(),
    "gaming_gamesession": Tenant(),
    "gaming_launchtoken": Tenant(owner=_via("gaming_gamesession", "session_id")),
    "gaming_wsticket": Tenant(owner=_via("gaming_gamesession", "session_id")),
    "gaming_bet": Tenant(),
    "gaming_roundoperatorexposure": Tenant(),
    "wallet_sandboxwalletaccount": Tenant(),
    "wallet_sandboxwalletentry": Tenant(owner=_via("wallet_sandboxwalletaccount", "account_id")),
    "wallet_wallettransaction": Tenant(),
    "wallet_wallettxattempt": Tenant(owner=_via("wallet_wallettransaction", "transaction_id")),
    "wallet_ledgerentry": Tenant(),
    "wallet_settlement": Tenant(owner=_via("gaming_bet", "bet_id")),
    "wallet_reconciliationrun": Tenant(),
    "wallet_discrepancy": Tenant(),
    "wallet_operatorreconcursor": Tenant(),
    "portal_staffuser": Tenant(privileges=("INSERT", "UPDATE")),
    "portal_staffsession": Tenant(
        owner=_via("portal_staffuser", "user_id"), privileges=("UPDATE",)
    ),
    # Appends go through audit.record(), which leaves the scope (one global hash chain).
    "portal_auditevent": Tenant(),
}

# Not operator-owned; readable by the portal.
GLOBAL_READ = {
    "operators_market",
    "gaming_gameround",
    "gaming_gameruleset",
    "gaming_streamconfig",
}

# Never reachable from the portal role.
PLATFORM_ONLY = {
    "django_migrations",
    "django_content_type",
    "django_session",
    "django_admin_log",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "auth_user",
    "auth_user_groups",
    "auth_user_user_permissions",
    "operators_requestnonce",
    "gaming_streamcursor",
    "gaming_processedevent",
    "wallet_outboxevent",
    "console_platformstaff",
    "console_passkey",
    "console_platformsession",
    "console_approvalrequest",
}


def role() -> str:
    name: str = settings.PORTAL_DB_ROLE
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name):
        raise ImproperlyConfigured("PORTAL_DB_ROLE must be a plain lower-case identifier")
    return name


# ---- request scope -------------------------------------------------------------------------

_scope: ContextVar[str | None] = ContextVar("lr_tenant_scope", default=None)


def current_operator() -> str | None:
    return _scope.get()


@contextmanager
def scoped(operator_id: Any) -> Iterator[None]:
    """Run the block as the portal role, seeing only `operator_id`'s rows (one transaction)."""
    current = _scope.get()
    if current is not None:
        if current != str(operator_id):
            raise RuntimeError("cannot switch tenants inside a tenant scope")
        yield  # a scoped view delegating to another scoped view
        return
    with transaction.atomic():
        _enter(str(operator_id))
        token = _scope.set(str(operator_id))
        try:
            yield
        finally:
            _scope.reset(token)
        # Normal exit: drop the role before the savepoint is released, so code that runs later
        # in an enclosing transaction (tests, nested callers) is not left inside the scope. On
        # an exception the rollback of this block undoes the SET LOCALs anyway.
        _leave()


@contextmanager
def unscoped() -> Iterator[None]:
    """Temporarily leave the tenant scope (platform privileges). Use sparingly and explicitly."""
    operator = _scope.get()
    if operator is None:
        yield
        return
    _leave()
    token = _scope.set(None)
    try:
        with transaction.atomic():  # a failure inside rolls back to here, keeping us usable
            yield
    finally:
        _scope.reset(token)
        _enter(operator)


def _enter(operator_id: str) -> None:
    with connection.cursor() as cur:
        cur.execute(f'SET LOCAL ROLE "{role()}"')
        cur.execute("SELECT set_config('app.operator_id', %s, true)", [operator_id])


def _leave() -> None:
    with connection.cursor() as cur:
        cur.execute("SET LOCAL ROLE NONE")
        cur.execute("SELECT set_config('app.operator_id', '', true)")


# ---- schema --------------------------------------------------------------------------------


def platform_tables() -> set[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s",
            [SCHEMA],
        )
        return {r[0] for r in cur.fetchall()}


def unclassified() -> set[str]:
    return platform_tables() - set(TENANT) - GLOBAL_READ - PLATFORM_ONLY


def _ensure_role(cur: Any, name: str) -> None:
    cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    row = cur.fetchone()
    superuser = bool(row and row[0])
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name])
    if cur.fetchone() is None:
        try:
            with transaction.atomic():
                cur.execute(f'CREATE ROLE "{name}" NOLOGIN')
        except Exception as exc:
            raise ImproperlyConfigured(
                f"database role {name!r} is missing and this user cannot create it; run "
                "infra/postgres/roles.sql as a superuser (ADR-019)"
            ) from exc
    if superuser:
        return
    cur.execute("SELECT pg_has_role(current_user, %s, 'SET')", [name])
    if not cur.fetchone()[0]:
        try:
            with transaction.atomic():
                cur.execute(f'GRANT "{name}" TO CURRENT_USER')
        except Exception as exc:
            raise ImproperlyConfigured(
                f"the platform database user must be able to SET ROLE {name}; "
                f'GRANT "{name}" TO <platform user> as a superuser (ADR-019)'
            ) from exc


def apply() -> None:
    """Idempotently (re)apply grants and policies from the classification above."""
    name = role()
    existing = platform_tables()
    with transaction.atomic(), connection.cursor() as cur:
        _ensure_role(cur, name)
        cur.execute(f'GRANT USAGE ON SCHEMA {SCHEMA} TO "{name}"')
        cur.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM "{name}"')
        cur.execute(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM "{name}"')
        for table in sorted(GLOBAL_READ & existing):
            cur.execute(f'GRANT SELECT ON {SCHEMA}.{table} TO "{name}"')
        for table, spec in sorted(TENANT.items()):
            if table not in existing:
                continue
            qualified = f"{SCHEMA}.{table}"
            for privilege in ("SELECT", *spec.privileges):
                cur.execute(f'GRANT {privilege} ON {qualified} TO "{name}"')
            cur.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
            cur.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {qualified}")
            check = f"{spec.owner} = {_OPERATOR}"
            cur.execute(
                f'CREATE POLICY tenant_isolation ON {qualified} FOR ALL TO "{name}" '
                f"USING ({check}) WITH CHECK ({check})"
            )
