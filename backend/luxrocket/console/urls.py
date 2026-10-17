from django.urls import path

from luxrocket.console import views as v

# Read-only for anything round-related: there is no route that writes rt.* or an outcome
# (AC-ADM-2, verified by tests/test_console.py).
urlpatterns = [
    path("auth/login", v.login),
    path("auth/passkey/options", v.passkey_options),
    path("auth/passkey/verify", v.passkey_verify),
    path("auth/passkey/register/options", v.passkey_register_options),
    path("auth/passkey/register", v.passkey_register),
    path("auth/logout", v.logout),
    path("me", v.me),
    path("me/password", v.change_password),
    path("overview", v.overview),
    path("markets", v.markets),
    path("markets/<str:country>", v.set_market),
    path("operators", v.operators),
    path("operators/<str:op_id>", v.operator_detail),
    path("operators/<str:op_id>/suspend", v.suspend_operator),
    path("operators/<str:op_id>/promote", v.promote_operator),
    path("operators/<str:op_id>/approvals", v.request_approval),
    path("operators/<str:op_id>/credentials/<str:kid>/revoke", v.revoke_operator_credential),
    path("approvals", v.approvals),
    path("approvals/<str:approval_id>/<str:decision>", v.decide_approval),
    path("finance/pending", v.pending_transactions),
    path("finance/transactions/<str:tx_id>/retry", v.retry_transaction),
    path("finance/bets", v.bets),
    path("finance/bets/<str:bet_id>", v.bet_timeline),
    path("finance/discrepancies", v.discrepancies),
    path("finance/discrepancies/<str:item_id>/resolve", v.resolve_discrepancy),
    path("games/rulesets", v.game_rulesets),
    path("games/streams", v.game_streams),
    path("games/seed-chains", v.seed_chains),
    path("rounds", v.rounds),
    path("rounds/<str:round_id>", v.round_detail),
    path("staff", v.staff),
    path("staff/<str:staff_id>", v.update_staff),
    path("staff/<str:staff_id>/reset-passkeys", v.reset_staff_passkeys),
    path("audit", v.audit_log),
    path("audit/verify", v.audit_verify),
]
