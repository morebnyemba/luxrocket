from django.contrib import admin

from luxrocket.operators.models import (
    Market,
    Operator,
    OperatorCredential,
    OperatorCurrencyLimit,
    OperatorDomain,
    OperatorJurisdiction,
)


class LimitInline(admin.TabularInline):  # type: ignore[type-arg]
    model = OperatorCurrencyLimit
    extra = 0


class DomainInline(admin.TabularInline):  # type: ignore[type-arg]
    model = OperatorDomain
    extra = 0


class JurisdictionInline(admin.TabularInline):  # type: ignore[type-arg]
    model = OperatorJurisdiction
    extra = 0


@admin.register(Operator)
class OperatorAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("legal_name", "public_id", "status", "real_money_enabled", "stream_slug")
    list_filter = ("status", "real_money_enabled")
    search_fields = ("legal_name", "public_id")
    readonly_fields = ("public_id", "real_money_enabled")  # real money only via approval flow
    inlines = [LimitInline, DomainInline, JurisdictionInline]


@admin.register(OperatorCredential)
class CredentialAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("kid", "operator", "algorithm", "status", "created_at", "last_used_at")
    list_filter = ("status",)
    readonly_fields = ("kid", "operator", "algorithm", "public_key", "created_at", "last_used_at")
    fields = ("kid", "operator", "algorithm", "status", "created_at", "last_used_at")

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False  # keys are issued through the operator portal / seed command


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Owner-only in production (ADR-026); grant this permission to PLAT_OWNER alone."""

    list_display = ("country_code", "status", "evidence_ref", "changed_at")
    list_filter = ("status",)
