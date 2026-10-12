"""Row-level security for the operator portal (ADR-019 §3)."""

import pytest
from django.db import ProgrammingError, connection, transaction
from django.utils import timezone

from luxrocket.console.models import PlatformStaff
from luxrocket.core import tenancy
from luxrocket.gaming.models import GameSession, PlayerRef
from luxrocket.operators.models import Operator, OperatorCredential
from luxrocket.portal import audit
from luxrocket.portal.models import AuditEvent
from luxrocket.wallet.models import OutboxEvent
from tests.factories import create_session, make_operator

pytestmark = pytest.mark.django_db


def whoami() -> tuple[str, str]:
    with connection.cursor() as cur:
        cur.execute("SELECT current_user, current_setting('app.operator_id', true)")
        user, op = cur.fetchone()
    return user, op or ""


def denied(fn) -> bool:
    try:
        with transaction.atomic():
            fn()
    except ProgrammingError as exc:
        return "permission denied" in str(exc) or "row-level security" in str(exc)
    return False


def test_every_platform_table_is_classified():
    assert tenancy.unclassified() == set()
    assert not set(tenancy.TENANT) & (tenancy.GLOBAL_READ | tenancy.PLATFORM_ONLY)


def test_unfiltered_queries_see_only_the_scoped_operator(client):
    a, b = make_operator("A"), make_operator("B")
    create_session(client, a, "pa")
    create_session(client, b, "pb")
    outside = whoami()

    with tenancy.scoped(a.operator.pk):
        assert whoami() == (tenancy.role(), str(a.operator.pk))
        # Deliberately unscoped ORM queries: RLS filters them.
        assert list(Operator.objects.values_list("pk", flat=True)) == [a.operator.pk]
        assert set(GameSession.objects.values_list("operator_id", flat=True)) == {a.operator.pk}
        assert set(PlayerRef.objects.values_list("external_player_id", flat=True)) == {"pa"}
        assert OperatorCredential.objects.filter(operator=b.operator).count() == 0
        # Writing another tenant's rows is refused by the policy's WITH CHECK.
        assert OperatorCredential.objects.filter(operator=b.operator).update(status="REVOKED") == 0
        assert denied(
            lambda: OperatorCredential.objects.create(
                operator=b.operator, kid="k_forged", public_key=b"\x00" * 32
            )
        )

    assert whoami() == outside
    assert OperatorCredential.objects.filter(operator=b.operator, status="REVOKED").count() == 0


def test_platform_tables_and_privileged_columns_are_out_of_reach():
    a = make_operator("A")
    PlatformStaff.objects.create(email="x@lux.test", role="OPS", password_hash="x")
    with tenancy.scoped(a.operator.pk):
        assert denied(lambda: list(PlatformStaff.objects.all()))
        assert denied(lambda: list(OutboxEvent.objects.all()))
        # The portal may edit wallet routing on its own row, never its licence state.
        Operator.objects.filter(pk=a.operator.pk).update(wallet_debit_timeout_ms=500)
        assert denied(
            lambda: Operator.objects.filter(pk=a.operator.pk).update(real_money_enabled=True)
        )
        assert denied(lambda: AuditEvent.objects.filter(operator=a.operator).delete())
    a.operator.refresh_from_db()
    assert a.operator.wallet_debit_timeout_ms == 500 and not a.operator.real_money_enabled


def test_audit_appends_leave_the_scope_and_keep_one_chain():
    a, b = make_operator("A"), make_operator("B")
    audit.record(realm="OPERATOR", actor="b@x", action="x", operator_id=b.operator.pk)
    with tenancy.scoped(a.operator.pk):
        event = audit.record(realm="OPERATOR", actor="a@x", action="y", operator_id=a.operator.pk)
        assert whoami()[0] == tenancy.role()  # back inside after the append
        assert [e.actor for e in AuditEvent.objects.all()] == ["a@x"]
    previous = AuditEvent.objects.get(actor="b@x")
    assert event.prev_hash == previous.hash
    assert audit.verify_chain() == (True, None)


def test_a_failure_inside_the_scope_does_not_leak_the_role():
    a, b = make_operator("A"), make_operator("B")
    outside = whoami()
    with pytest.raises(ZeroDivisionError), tenancy.scoped(a.operator.pk):
        _ = 1 / 0
    assert whoami() == outside
    with tenancy.scoped(a.operator.pk), pytest.raises(RuntimeError):
        with tenancy.scoped(b.operator.pk):
            pass
    assert whoami() == outside
    assert timezone.now()  # connection still usable
