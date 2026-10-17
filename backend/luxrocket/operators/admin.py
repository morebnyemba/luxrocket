from django.contrib import admin

from luxrocket.operators.models import (
    Market,
    Operator,
    OperatorCredential,
    OperatorCurrencyLimit,
    OperatorDomain,
    OperatorJurisdiction,
    WebhookDelivery,
    WebhookEndpoint,
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


class WebhookInline(admin.TabularInline):  # type: ignore[type-arg]
    model = WebhookEndpoint
    extra = 0


@admin.register(Operator)
class OperatorAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "legal_name",
        "public_id",
        "status",
        "real_money_enabled",
        "wallet_kind",
        "stream_slug",
    )
    list_filter = ("status", "real_money_enabled", "wallet_kind")
    search_fields = ("legal_name", "public_id")
    readonly_fields = ("public_id", "real_money_enabled")  # real money only via approval flow
    inlines = [LimitInline, DomainInline, JurisdictionInline, WebhookInline]


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


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Delivery log (doc 09 §7). Re-queue a FAILED delivery by setting it back to PENDING."""

    list_display = ("event_id", "type", "operator", "status", "attempts", "last_status_code")
    list_filter = ("status", "type")
    search_fields = ("event_id",)
    readonly_fields = (
        "event_id",
        "endpoint",
        "operator",
        "type",
        "payload",
        "attempts",
        "last_status_code",
        "last_error",
        "created_at",
        "delivered_at",
    )

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False
