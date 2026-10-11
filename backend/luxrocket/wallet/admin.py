from django.contrib import admin

from luxrocket.core.admin_base import ReadOnlyAdmin
from luxrocket.wallet.models import LedgerEntry, Settlement, WalletTransaction, WalletTxAttempt


class AttemptInline(admin.TabularInline):  # type: ignore[type-arg]
    model = WalletTxAttempt
    extra = 0
    can_delete = False
    readonly_fields = ("attempt_no", "outcome", "operator_code", "latency_ms", "created_at")

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(WalletTransaction)
class WalletTransactionAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "type",
        "amount_minor",
        "currency",
        "status",
        "attempt_count",
        "created_at",
    )
    list_filter = ("type", "status", "operator")
    inlines = [AttemptInline]


@admin.register(Settlement)
class SettlementAdmin(ReadOnlyAdmin):
    list_display = ("bet", "outcome", "payout_minor", "multiplier_x10000", "status", "confirmed_at")
    list_filter = ("outcome", "status")


@admin.register(LedgerEntry)
class LedgerAdmin(ReadOnlyAdmin):
    list_display = ("journal_id", "account", "amount_minor", "currency", "memo", "created_at")
    list_filter = ("account", "currency", "operator")
