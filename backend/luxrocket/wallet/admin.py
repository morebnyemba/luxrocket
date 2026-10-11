from django import forms
from django.contrib import admin
from django.utils import timezone

from luxrocket.core.admin_base import ReadOnlyAdmin
from luxrocket.wallet.models import (
    Discrepancy,
    LedgerEntry,
    ReconciliationRun,
    Settlement,
    WalletTransaction,
    WalletTxAttempt,
)


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


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(ReadOnlyAdmin):
    list_display = (
        "started_at",
        "kind",
        "operator",
        "status",
        "checked",
        "opened",
        "auto_resolved",
        "note",
    )
    list_filter = ("kind", "status")


class DiscrepancyForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = Discrepancy
        fields = ("status", "resolution_note")

    def clean(self):  # type: ignore[no-untyped-def]
        data = super().clean()
        if data.get("status") == Discrepancy.Status.RESOLVED and not data.get("resolution_note"):
            raise forms.ValidationError("A resolution note is mandatory (doc 08 §8).")
        if data.get("status") == Discrepancy.Status.AUTO_RESOLVED:
            raise forms.ValidationError("Only reconciliation may auto-resolve.")
        return data


@admin.register(Discrepancy)
class DiscrepancyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Discrepancy queue. Closing one never moves money: corrections are new transactions."""

    form = DiscrepancyForm
    list_display = ("created_at", "kind", "severity", "subject", "operator", "status")
    list_filter = ("status", "severity", "kind")
    search_fields = ("subject",)
    readonly_fields = (
        "run",
        "operator",
        "kind",
        "severity",
        "subject",
        "detail",
        "resolved_by",
        "created_at",
        "resolved_at",
    )

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def save_model(self, request, obj, form, change):  # type: ignore[no-untyped-def]
        if obj.status == Discrepancy.Status.RESOLVED and obj.resolved_at is None:
            obj.resolved_at = timezone.now()
            obj.resolved_by = request.user.get_username()
        super().save_model(request, obj, form, change)
