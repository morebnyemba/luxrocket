from django.urls import path

from luxrocket.portal import views as v

urlpatterns = [
    path("auth/login", v.login),
    path("auth/mfa", v.mfa),
    path("auth/logout", v.logout),
    path("me", v.me),
    path("me/password", v.change_password),
    path("me/mfa/setup", v.mfa_setup),
    path("me/mfa/enable", v.mfa_enable),
    path("me/sessions", v.my_sessions),
    path("me/sessions/<str:session_id>/revoke", v.revoke_my_session),
    path("overview", v.overview),
    path("bets", v.bets),
    path("bets/<str:bet_id>", v.bet_detail),
    path("rounds", v.rounds),
    path("discrepancies", v.discrepancies),
    path("credentials", v.credentials),
    path("credentials/<str:kid>/revoke", v.revoke_credential),
    path("wallet", v.wallet),
    path("wallet/conformance", v.wallet_conformance),
    path("webhooks", v.webhooks),
    path("webhooks/<str:endpoint_id>/disable", v.disable_webhook),
    path("webhook-deliveries", v.webhook_deliveries),
    path("webhook-deliveries/<str:delivery_id>/replay", v.replay_delivery),
    path("users", v.users),
    path("users/<str:user_id>", v.update_user),
    path("users/<str:user_id>/reset-mfa", v.reset_user_mfa),
    path("audit", v.audit_log),
]
