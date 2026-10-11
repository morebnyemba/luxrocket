"""Game release controls (doc 12 §3.3): certified rulesets, four-eyes binding, integrity check."""

import pytest
from django.db import DatabaseError, transaction

from luxrocket.console.models import Role
from luxrocket.gaming.models import GameRound, GameRuleset, StreamConfig
from luxrocket.wallet.models import OutboxEvent
from tests.factories import INTERNAL
from tests.rt import RoundSim
from tests.test_console import call, signed_in
from tests.test_money_path import send

pytestmark = pytest.mark.django_db


def draft(client, code="LR-HI-98", edge=200, max_x=50_000_000):
    return call(
        client,
        "post",
        "games/rulesets",
        {"code": code, "house_edge_bp": edge, "max_multiplier_x10000": max_x},
    )


def test_default_ruleset_is_bound_and_honestly_uncertified():
    default = GameRuleset.objects.get(code="LR-STD-97")
    assert default.status == "APPROVED" and default.rtp_bp == 9700
    assert "NOT CERTIFIED" in default.certification_ref
    assert StreamConfig.objects.get(stream_slug="global").ruleset_id == "LR-STD-97"


def test_draft_bounds_are_enforced(client):
    gr = signed_in(Role.GAME_RELEASE, "gr@lux.test")
    assert draft(gr, edge=50).json()["code"] == "CONFIG_NOT_PERMITTED"  # RTP 99.5% too generous
    assert draft(gr, edge=2000).json()["code"] == "CONFIG_NOT_PERMITTED"
    assert draft(gr, max_x=200_000_000).json()["code"] == "CONFIG_NOT_PERMITTED"  # beyond curve
    assert draft(gr, code="bad code!").status_code == 422
    r = draft(gr)
    assert r.status_code == 201 and r.json()["rtp_bp"] == 9800 and r.json()["status"] == "DRAFT"


def test_approval_needs_a_certificate_and_a_second_person(client):
    gr = signed_in(Role.GAME_RELEASE, "gr@lux.test")
    draft(gr)
    req = {"action": "APPROVE_RULESET", "subject": "LR-HI-98", "reason": "lab report in"}
    assert call(gr, "post", "approvals", req).json()["code"] == "PRECONDITION_FAILED"
    r = call(gr, "post", "approvals", req | {"payload": {"certification_ref": "GLI-19-2026-114"}})
    assert r.status_code == 201
    approval = r.json()["id"]
    assert (
        call(gr, "post", f"approvals/{approval}/approve", {"note": "x"}).json()["code"]
        == "SELF_APPROVAL"
    )
    ops = signed_in(Role.OPS, "ops@lux.test")
    assert (
        call(ops, "post", f"approvals/{approval}/approve", {"note": "x"}).json()["code"]
        == "FORBIDDEN"
    )
    risk = signed_in(Role.RISK, "risk@lux.test")
    assert (
        call(
            risk,
            "post",
            f"approvals/{approval}/approve",
            {"note": "certificate matches parameters"},
        ).status_code
        == 200
    )
    rs = GameRuleset.objects.get(code="LR-HI-98")
    assert rs.status == "APPROVED" and rs.certification_ref == "GLI-19-2026-114"
    assert rs.approved_by == "risk@lux.test"


def test_approved_rulesets_are_immutable_in_the_database():
    rs = GameRuleset.objects.get(code="LR-STD-97")
    with pytest.raises(DatabaseError), transaction.atomic():
        GameRuleset.objects.filter(pk=rs.pk).update(house_edge_bp=100)
    with pytest.raises(DatabaseError), transaction.atomic():
        GameRuleset.objects.filter(pk=rs.pk).delete()
    GameRuleset.objects.filter(pk=rs.pk).update(status="RETIRED")  # retiring is allowed
    with pytest.raises(DatabaseError), transaction.atomic():
        GameRuleset.objects.filter(pk=rs.pk).update(status="APPROVED")


def test_binding_is_four_eyes_and_reaches_phoenix_through_the_outbox(client):
    GameRuleset.objects.create(
        code="LR-HI-98",
        house_edge_bp=200,
        max_multiplier_x10000=50_000_000,
        status="APPROVED",
        certification_ref="GLI-1",
        created_by="t",
    )
    gr = signed_in(Role.GAME_RELEASE, "gr@lux.test")
    unapproved = call(
        gr,
        "post",
        "approvals",
        {
            "action": "BIND_RULESET",
            "subject": "global",
            "reason": "r",
            "payload": {"ruleset": "LR-NOPE"},
        },
    )
    assert unapproved.json()["code"] == "PRECONDITION_FAILED"
    r = call(
        gr,
        "post",
        "approvals",
        {
            "action": "BIND_RULESET",
            "subject": "global",
            "reason": "promo season",
            "payload": {"ruleset": "LR-HI-98"},
        },
    )
    assert r.status_code == 201
    sa = signed_in(Role.SUPERADMIN, "sa@lux.test")
    assert (
        call(sa, "post", f"approvals/{r.json()['id']}/approve", {"note": "approved"}).status_code
        == 200
    )
    cfg = StreamConfig.objects.get(stream_slug="global")
    assert cfg.ruleset_id == "LR-HI-98" and cfg.version == 2
    event = OutboxEvent.objects.get(type="stream.config")
    assert event.payload == {
        "stream": "global",
        "version": 2,
        "ruleset": {"code": "LR-HI-98", "house_edge_bp": 200, "max_multiplier_x10000": 50_000_000},
    }
    boot = client.get("/internal/v1/streams/global/config", **INTERNAL)
    assert boot.json()["version"] == 2
    assert client.get("/internal/v1/streams/nope/config", **INTERNAL).status_code == 404
    streams = call(gr, "get", "games/streams").json()["streams"]
    assert streams[0]["desired"] == {"ruleset": "LR-HI-98", "version": 2}


def test_a_round_on_unapproved_parameters_never_verifies(client):
    sim = RoundSim.with_min_crash(20_000)
    send(client, sim.created(ruleset_code="LR-STD-97", ruleset_version=1, house_edge_bp=100))
    rnd = GameRound.objects.get(pk=sim.round_id)
    assert rnd.ruleset_ok is False
    send(client, sim.opened(), sim.launched(), sim.crashed())
    rnd.refresh_from_db()
    assert rnd.outcome_verified is False
    assert rnd.settlement_status == GameRound.Settlement.NEEDS_ATTENTION


def test_a_round_on_the_bound_ruleset_verifies(client):
    sim = RoundSim.with_min_crash(20_000)
    send(
        client,
        sim.created(ruleset_code="LR-STD-97", ruleset_version=1),
        sim.opened(),
        sim.launched(),
        sim.crashed(),
    )
    rnd = GameRound.objects.get(pk=sim.round_id)
    assert rnd.ruleset_ok is True and rnd.outcome_verified is True
    assert rnd.ruleset_code == "LR-STD-97" and rnd.ruleset_version == 1
