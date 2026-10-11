"""Operators (tenants), credentials, domains, limits and the owner-controlled market registry."""

from django.db import models

from luxrocket.core.ids import public_id, uuid7


class WalletKind(models.TextChoices):
    """Where a session's money moves (snapshotted onto each session at creation)."""

    SIMULATED = "SIMULATED"  # built-in sandbox wallet; SANDBOX sessions only
    SEAMLESS_V1 = "SEAMLESS_V1"  # operator implements LUX Seamless Wallet v1 (doc 09 §6)


class Operator(models.Model):
    class Status(models.TextChoices):
        ONBOARDING = "ONBOARDING"
        SANDBOX = "SANDBOX"
        LIVE = "LIVE"
        SUSPENDED = "SUSPENDED"
        TERMINATED = "TERMINATED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    public_id = models.CharField(max_length=40, unique=True, editable=False)
    legal_name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SANDBOX)
    real_money_enabled = models.BooleanField(default=False)
    stream_slug = models.CharField(max_length=64, default="global")
    wallet_kind = models.CharField(
        max_length=16, choices=WalletKind.choices, default=WalletKind.SIMULATED
    )
    # Base URL of the operator's wallet ({base}/debit, /credit, /rollback, /balance).
    wallet_base_url = models.CharField(max_length=500, blank=True)
    wallet_debit_timeout_ms = models.PositiveIntegerField(default=900)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        from luxrocket.wallet.seamless import WalletConfigError, validate_base_url

        if self.wallet_kind == WalletKind.SEAMLESS_V1:
            try:
                validate_base_url(self.wallet_base_url)
            except WalletConfigError as exc:
                raise ValidationError({"wallet_base_url": str(exc)}) from exc
        elif self.real_money_enabled:
            raise ValidationError({"wallet_kind": "real money requires a seamless wallet"})

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.public_id:
            self.public_id = public_id("op", self.id)
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def __str__(self) -> str:
        return f"{self.legal_name} ({self.public_id})"


class OperatorCredential(models.Model):
    """Operator API signing key. Ed25519: only the public key is stored (ADR-010)."""

    class Algorithm(models.TextChoices):
        ED25519 = "ED25519"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="credentials")
    kid = models.CharField(max_length=64, unique=True)
    algorithm = models.CharField(
        max_length=16, choices=Algorithm.choices, default=Algorithm.ED25519
    )
    public_key = models.BinaryField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)


class RequestNonce(models.Model):
    """Replay protection for signed operator requests (10-minute window)."""

    kid = models.CharField(max_length=64)
    nonce = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kid", "nonce"], name="uniq_nonce_per_kid")]


class IdempotencyRecord(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE)
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["operator", "key"], name="uniq_idempotency_key")
        ]


class OperatorDomain(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="domains")
    origin = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["operator", "origin"], name="uniq_operator_origin")
        ]


class OperatorCurrencyLimit(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="limits")
    currency = models.CharField(max_length=3)
    exponent = models.PositiveSmallIntegerField(default=2)
    min_stake_minor = models.BigIntegerField()
    max_stake_minor = models.BigIntegerField()
    max_win_minor = models.BigIntegerField()
    round_exposure_limit_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["operator", "currency"], name="uniq_operator_ccy"),
            models.CheckConstraint(
                condition=models.Q(min_stake_minor__gt=0)
                & models.Q(max_stake_minor__gte=models.F("min_stake_minor"))
                & models.Q(max_win_minor__gt=0)
                & models.Q(round_exposure_limit_minor__gt=0),
                name="limits_sane",
            ),
        ]


class Market(models.Model):
    """Platform-level country registry; only PLAT_OWNER may change it (ADR-026)."""

    class Status(models.TextChoices):
        DISABLED = "DISABLED"
        SANDBOX = "SANDBOX"
        REAL = "REAL"

    country_code = models.CharField(max_length=2, primary_key=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.SANDBOX)
    evidence_ref = models.CharField(max_length=500, blank=True)
    changed_at = models.DateTimeField(auto_now=True)

    def allows(self, mode: str) -> bool:
        if mode == "SANDBOX":
            return self.status in (self.Status.SANDBOX, self.Status.REAL)
        return self.status == self.Status.REAL


class OperatorJurisdiction(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="jurisdictions")
    country_code = models.CharField(max_length=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["operator", "country_code"], name="uniq_op_country")
        ]


class WebhookEndpoint(models.Model):
    """Where we notify an operator of settlement events (doc 09 §7)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="webhooks")
    url = models.CharField(max_length=500)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["operator", "url"], name="uniq_webhook_url")]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        from luxrocket.wallet.seamless import WalletConfigError, validate_base_url

        try:
            validate_base_url(self.url)
        except WalletConfigError as exc:
            raise ValidationError({"url": str(exc).replace("wallet base", "webhook")}) from exc


class WebhookDelivery(models.Model):
    """Transactional outbox of webhook events, one row per (event, endpoint)."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        DELIVERED = "DELIVERED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    event_id = models.CharField(max_length=40, db_index=True)
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE)
    type = models.CharField(max_length=40)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "next_attempt_at"])]
        constraints = [
            models.UniqueConstraint(fields=["event_id", "endpoint"], name="uniq_event_endpoint")
        ]
