"""Operators (tenants), credentials, domains, limits and the owner-controlled market registry."""

from django.db import models

from luxrocket.core.ids import public_id, uuid7


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
    created_at = models.DateTimeField(auto_now_add=True)

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
