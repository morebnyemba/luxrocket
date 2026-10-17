"""Operator portal staff, sessions and the hash-chained audit log (doc 13, doc 15 §4)."""

from django.db import models

from luxrocket.core.ids import uuid7
from luxrocket.operators.models import Operator


class Role(models.TextChoices):
    OWNER = "OP_OWNER"
    ADMIN = "OP_ADMIN"
    DEVELOPER = "OP_DEVELOPER"
    FINANCE = "OP_FINANCE"
    SUPPORT = "OP_SUPPORT"
    VIEWER = "OP_VIEWER"


class StaffUser(models.Model):
    """Operator staff (realm OPERATOR). One account per operator; no operator switching."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        DISABLED = "DISABLED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="staff")
    email = models.EmailField()
    password_hash = models.CharField(max_length=256)
    must_change_password = models.BooleanField(default=True)
    role = models.CharField(max_length=16, choices=Role.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    totp_secret_enc = models.BinaryField(null=True, blank=True)  # AES-GCM, key outside the DB
    mfa_enabled = models.BooleanField(default=False)
    last_totp_step = models.BigIntegerField(default=0)  # a code is accepted at most once
    failed_logins = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["email"], name="uniq_staff_email")]


class StaffSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(StaffUser, on_delete=models.CASCADE, related_name="sessions")
    mfa_pending = models.BooleanField(default=False)  # password ok, second factor still due
    mfa_at = models.DateTimeField(null=True, blank=True)  # last second-factor check (step-up)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)


class AuditEvent(models.Model):
    """Append-only, hash-chained: hash = sha256(prev_hash || canonical(event)). DB-enforced."""

    seq = models.BigAutoField(primary_key=True)
    at = models.DateTimeField()
    realm = models.CharField(max_length=10)
    operator = models.ForeignKey(Operator, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.CharField(max_length=200)
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=120, blank=True)
    data = models.JSONField(default=dict)
    ip = models.GenericIPAddressField(null=True, blank=True)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        indexes = [models.Index(fields=["operator", "seq"])]
