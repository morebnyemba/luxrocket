from django.contrib import admin
from django.urls import path

from luxrocket.api import demo_views, game_views, internal_views, operator_views
from luxrocket.core.views import healthz, platform_keys

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path(".well-known/luxrocket-keys.json", platform_keys),
    # Operator API (signed, doc 09)
    path("operator/v1/sessions", operator_views.create_session),
    path("operator/v1/sessions/<str:session_id>/revoke", operator_views.revoke_session),
    path("operator/v1/bets/<str:bet_id>", operator_views.get_bet),
    path("operator/v1/rounds/<str:round_id>", operator_views.get_round),
    # Game API (bearer game-session token)
    path("game/v1/sessions/exchange", game_views.exchange),
    path("game/v1/sessions/renew", game_views.renew),
    path("game/v1/ws-tickets", game_views.ws_ticket),
    path("game/v1/config", game_views.config),
    path("game/v1/me/bets", game_views.my_bets),
    path("game/v1/rounds/recent", game_views.recent_rounds),
    path("game/v1/rounds/<uuid:round_id>/verification", game_views.verification),
    # Internal API (Phoenix only)
    path("internal/v1/ws-tickets/consume", internal_views.consume_ws_ticket),
    path("internal/v1/sessions/<str:session_id>/status", internal_views.session_status),
    path("internal/v1/bets", internal_views.place_bet),
    path("internal/v1/rt-events", internal_views.rt_events),
    # Development-only demo operator page (404 unless DEBUG and DEMO_PAGES)
    path("demo/operator", demo_views.demo_operator),
    # Interim back-office for platform staff (Next.js consoles replace it, Phase F)
    path("django-admin/", admin.site.urls),
]
