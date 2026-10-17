from django.contrib import admin

from luxrocket.core.admin_base import ReadOnlyAdmin
from luxrocket.gaming.models import Bet, GameRound, GameSession, PlayerRef


@admin.register(GameRound)
class RoundAdmin(ReadOnlyAdmin):
    list_display = (
        "number",
        "state",
        "crash_x10000",
        "outcome_verified",
        "settlement_status",
        "updated_at",
    )
    list_filter = ("state", "settlement_status", "outcome_verified")
    ordering = ("-number",)


@admin.register(Bet)
class BetAdmin(ReadOnlyAdmin):
    list_display = (
        "public_id",
        "operator",
        "panel",
        "stake_minor",
        "currency",
        "status",
        "cashout_x10000",
        "payout_minor",
        "created_at",
    )
    list_filter = ("status", "operator", "currency")
    search_fields = ("public_id",)
    ordering = ("-created_at",)


@admin.register(GameSession)
class SessionAdmin(ReadOnlyAdmin):
    list_display = ("public_id", "operator", "mode", "currency", "status", "expires_at")
    list_filter = ("status", "mode")
    search_fields = ("public_id",)


@admin.register(PlayerRef)
class PlayerAdmin(ReadOnlyAdmin):
    list_display = ("external_player_id", "operator", "country_code", "restricted", "created_at")
    search_fields = ("external_player_id",)
