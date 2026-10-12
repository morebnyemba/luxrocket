"""Wallet transactions, attempts, double-entry ledger, settlements and the outbox (doc 04 §4.5)."""

from django.db import models

from luxrocket.core.ids import uuid7
from luxrocket.gaming.models import Bet, PlayerRef
from luxrocket.operators.models import Operator


class SandboxWalletAccount(models.Model):
    """Simulated operator wallet for SANDBOX sessions (FR-043). Real money never touches this."""

    operator = models.ForeignKey(Operator, on_delete=models.CASCADE)
    player = models.ForeignKey(PlayerRef, on_delete=models.CASCADE)
    currency = models.CharField(max_length=3)
    balance_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "player", "currency"], name="uniq_sbx_acct"
            ),
            models.CheckConstraint(
                condition=models.Q(balance_minor__gte=0), name="sbx_non_negative"
            ),
        ]


class SandboxWalletEntry(models.Model):
    """Idempotency record of the simulated wallet, keyed by our transaction id (doc 09 §6.5)."""

    transaction_id = models.UUIDField(primary_key=True)
    account = models.ForeignKey(SandboxWalletAccount, on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    amount_minor = models.BigIntegerField()
    result = models.CharField(max_length=32)
    tombstone = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class WalletTransaction(models.Model):
    class Type(models.TextChoices):
        DEBIT = "DEBIT"
        CREDIT = "CREDIT"
        ROLLBACK = "ROLLBACK"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"
        UNKNOWN = "UNKNOWN"
        NEEDS_ATTENTION = "NEEDS_ATTENTION"

    id = models.UUIDField(primary_key=True)  # deterministic per (bet, type)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT)
    bet = models.ForeignKey(Bet, on_delete=models.PROTECT, related_name="transactions")
    type = models.CharField(max_length=8, choices=Type.choices)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    operator_code = models.CharField(max_length=32, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # A second credit (or debit, or rollback) for the same bet is impossible (T-07).
            models.UniqueConstraint(fields=["bet", "type"], name="uniq_tx_per_bet_type")
        ]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]


class WalletTxAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    transaction = models.ForeignKey(
        WalletTransaction, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_no = models.PositiveIntegerField()
    outcome = models.CharField(max_length=16)
    operator_code = models.CharField(max_length=32, blank=True)
    latency_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class LedgerEntry(models.Model):
    """Append-only double-entry postings; every journal_id sums to zero (doc 08 §7.1)."""

    class Account(models.TextChoices):
        PLAYER_WALLET = "player_wallet"
        BETS_IN_PLAY = "bets_in_play"
        PAYOUTS_PAYABLE = "payouts_payable"
        REFUNDS_PAYABLE = "refunds_payable"
        GAME_RESULT = "game_result"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    journal_id = models.UUIDField(db_index=True)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT)
    account = models.CharField(max_length=20, choices=Account.choices)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    bet = models.ForeignKey(Bet, on_delete=models.PROTECT, related_name="ledger_entries")
    memo = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class Settlement(models.Model):
    class Outcome(models.TextChoices):
        WIN = "WIN"
        LOSS = "LOSS"
        REFUND = "REFUND"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        CONFIRMED = "CONFIRMED"
        NEEDS_ATTENTION = "NEEDS_ATTENTION"

    bet = models.OneToOneField(Bet, on_delete=models.PROTECT, primary_key=True)
    outcome = models.CharField(max_length=8, choices=Outcome.choices)
    payout_minor = models.BigIntegerField(default=0)
    multiplier_x10000 = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class OutboxEvent(models.Model):
    """Transactional outbox for platform -> Phoenix events (ADR-015)."""

    event_id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    type = models.CharField(max_length=40)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)


class ReconciliationRun(models.Model):
    class Kind(models.TextChoices):
        INTERNAL = "INTERNAL"
        OPERATOR = "OPERATOR"

    class Status(models.TextChoices):
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        UNAVAILABLE = "UNAVAILABLE"  # operator lookup endpoint missing or failing
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    operator = models.ForeignKey(Operator, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    checked = models.PositiveIntegerField(default=0)
    opened = models.PositiveIntegerField(default=0)
    auto_resolved = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class Discrepancy(models.Model):
    """A reconciliation finding. Never edited into money: corrections are new transactions."""

    class Severity(models.TextChoices):
        WARNING = "WARNING"
        CRITICAL = "CRITICAL"

    class Status(models.TextChoices):
        OPEN = "OPEN"
        AUTO_RESOLVED = "AUTO_RESOLVED"
        RESOLVED = "RESOLVED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    run = models.ForeignKey(ReconciliationRun, on_delete=models.PROTECT, related_name="items")
    operator = models.ForeignKey(Operator, null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    severity = models.CharField(max_length=8, choices=Severity.choices)
    subject = models.CharField(max_length=60)  # bet / transaction / round public id
    detail = models.JSONField(default=dict)
    status = models.CharField(max_length=14, choices=Status.choices)
    resolution_note = models.TextField(blank=True)
    resolved_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # A finding stays one item until a human closes it, however many runs see it.
            models.UniqueConstraint(
                fields=["kind", "subject"],
                condition=models.Q(status="OPEN"),
                name="uniq_open_discrepancy",
            )
        ]
        indexes = [models.Index(fields=["status", "severity"])]


class OperatorReconCursor(models.Model):
    """Operator reconciliation is incremental over terminal transactions by updated_at."""

    operator = models.OneToOneField(Operator, on_delete=models.CASCADE, primary_key=True)
    last_updated_at = models.DateTimeField(null=True, blank=True)
