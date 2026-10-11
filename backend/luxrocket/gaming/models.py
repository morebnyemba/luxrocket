"""Players, sessions, credentials, rounds (projection of Phoenix facts) and bets (doc 04)."""

from django.db import models

from luxrocket.core.ids import public_id, uuid7
from luxrocket.operators.models import Operator


class PlayerRef(models.Model):
    """Pseudonymous operator player. No PII (NFR-010)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="players")
    external_player_id = models.CharField(max_length=128)
    display_alias = models.CharField(max_length=24, blank=True)
    country_code = models.CharField(max_length=2)
    restricted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "external_player_id"], name="uniq_player_per_operator"
            )
        ]


class GameSession(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        ACTIVE = "ACTIVE"
        EXPIRED = "EXPIRED"
        REVOKED = "REVOKED"

    class Mode(models.TextChoices):
        SANDBOX = "SANDBOX"
        REAL = "REAL"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    public_id = models.CharField(max_length=40, unique=True, editable=False)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="sessions")
    player = models.ForeignKey(PlayerRef, on_delete=models.PROTECT, related_name="sessions")
    currency = models.CharField(max_length=3)
    locale = models.CharField(max_length=16, default="en")
    mode = models.CharField(max_length=8, choices=Mode.choices)
    stream_slug = models.CharField(max_length=64)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    session_version = models.PositiveIntegerField(default=1)
    expires_at = models.DateTimeField()
    revoked_reason = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["operator", "player", "status"])]

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.public_id:
            self.public_id = public_id("ses", self.id)
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class LaunchToken(models.Model):
    token_hash = models.BinaryField(unique=True)
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class WsTicket(models.Model):
    token_hash = models.BinaryField(unique=True)
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class GameRound(models.Model):
    """Projection of an rt.round, written only by the journal consumer."""

    class Settlement(models.TextChoices):
        OPEN = "OPEN"
        SETTLING = "SETTLING"
        SETTLED = "SETTLED"
        NEEDS_ATTENTION = "NEEDS_ATTENTION"

    id = models.UUIDField(primary_key=True)
    stream_slug = models.CharField(max_length=64)
    number = models.BigIntegerField()
    state = models.CharField(max_length=16)
    commitment = models.CharField(max_length=64, blank=True)
    launch_at_ms = models.BigIntegerField(null=True, blank=True)
    crash_x10000 = models.IntegerField(null=True, blank=True)
    end_reason = models.CharField(max_length=16, blank=True)
    seed_hex = models.CharField(max_length=64, blank=True)
    salt_hex = models.CharField(max_length=128, blank=True)
    house_edge_bp = models.IntegerField(null=True, blank=True)
    max_multiplier_x10000 = models.IntegerField(null=True, blank=True)
    outcome_verified = models.BooleanField(null=True)
    settlement_status = models.CharField(
        max_length=16, choices=Settlement.choices, default=Settlement.OPEN
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["stream_slug", "number"], name="uniq_round_number")
        ]


class Bet(models.Model):
    class Status(models.TextChoices):
        PENDING_DEBIT = "PENDING_DEBIT"
        REJECTED = "REJECTED"
        DEBIT_UNKNOWN = "DEBIT_UNKNOWN"
        DEBITED = "DEBITED"
        ACTIVE = "ACTIVE"
        EXCLUDED = "EXCLUDED"
        CASHED_OUT = "CASHED_OUT"
        LOST = "LOST"
        VOIDED = "VOIDED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    public_id = models.CharField(max_length=40, unique=True, editable=False)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT)
    session = models.ForeignKey(GameSession, on_delete=models.PROTECT, related_name="bets")
    player = models.ForeignKey(PlayerRef, on_delete=models.PROTECT, related_name="bets")
    round_id = models.UUIDField(db_index=True)
    panel = models.PositiveSmallIntegerField()
    client_command_id = models.UUIDField()
    currency = models.CharField(max_length=3)
    stake_minor = models.BigIntegerField()
    auto_cashout_x10000 = models.IntegerField(null=True, blank=True)
    max_win_minor = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices)
    reject_code = models.CharField(max_length=32, blank=True)
    cashout_x10000 = models.IntegerField(null=True, blank=True)
    payout_minor = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # One bet per panel per player per round, across tabs and sessions (FR-025).
            models.UniqueConstraint(
                fields=["round_id", "operator", "player", "panel"], name="uniq_bet_per_panel"
            ),
            models.UniqueConstraint(
                fields=["round_id", "session", "client_command_id"], name="uniq_bet_command"
            ),
            models.CheckConstraint(condition=models.Q(stake_minor__gt=0), name="stake_positive"),
        ]
        indexes = [models.Index(fields=["operator", "created_at"])]

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.public_id:
            self.public_id = public_id("bet", self.id)
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class RoundOperatorExposure(models.Model):
    round_id = models.UUIDField()
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE)
    currency = models.CharField(max_length=3)
    exposure_minor = models.BigIntegerField(default=0)
    limit_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["round_id", "operator", "currency"], name="uniq_round_exposure"
            )
        ]


class StreamCursor(models.Model):
    """Last applied journal sequence per stream (ordered, gap-free application)."""

    stream_slug = models.CharField(max_length=64, primary_key=True)
    last_seq = models.BigIntegerField(default=0)
    # Highest coordinator fencing token seen; calls with a lower token are stale (ADR-004).
    max_fencing_token = models.BigIntegerField(default=0)


class ProcessedEvent(models.Model):
    """Inbox de-duplication for at-least-once delivery (ADR-015)."""

    event_id = models.UUIDField(primary_key=True)
    processed_at = models.DateTimeField(auto_now_add=True)
