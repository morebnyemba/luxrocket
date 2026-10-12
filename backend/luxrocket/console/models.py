"""Platform staff (realm PLATFORM), passkeys, sessions and four-eyes approvals (doc 12)."""

from django.db import models

from luxrocket.core.ids import uuid7
from luxrocket.operators.models import Operator


class Role(models.TextChoices):
    OWNER = "PLAT_OWNER"
    SUPERADMIN = "PLAT_SUPERADMIN"
    OPS = "PLAT_OPS"
    FINANCE = "PLAT_FINANCE"
    RISK = "PLAT_RISK"
    SUPPORT = "PLAT_SUPPORT"
    GAME_RELEASE = "PLAT_GAME_RELEASE"
    AUDITOR = "PLAT_AUDITOR"


class PlatformStaff(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        DISABLED = "DISABLED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=256)
    must_change_password = models.BooleanField(default=True)
    role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    webauthn_user_id = models.BinaryField(max_length=32)  # opaque handle, never the email
    failed_logins = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Passkey(models.Model):
    """A WebAuthn credential (hardware key / platform authenticator). MFA is mandatory."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    staff = models.ForeignKey(PlatformStaff, on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.BinaryField(max_length=1024)
    credential_id_hash = models.CharField(max_length=64, unique=True)
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    name = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)


class PlatformSession(models.Model):
    class Stage(models.TextChoices):
        ENROLL = "ENROLL"  # password ok, no passkey yet: may only register one
        PASSKEY = "PASSKEY"  # password ok, passkey assertion still due
        FULL = "FULL"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    token_hash = models.CharField(max_length=64, unique=True)
    staff = models.ForeignKey(PlatformStaff, on_delete=models.CASCADE, related_name="sessions")
    stage = models.CharField(max_length=8, choices=Stage.choices)
    mfa_at = models.DateTimeField(null=True, blank=True)
    challenge = models.BinaryField(null=True, blank=True)
    challenge_kind = models.CharField(max_length=12, blank=True)
    challenge_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)


class ApprovalRequest(models.Model):
    """Four-eyes: the requester can never be the approver (AC-ADM-3)."""

    class Action(models.TextChoices):
        ENABLE_REAL_MONEY = "ENABLE_REAL_MONEY"
        REACTIVATE_OPERATOR = "REACTIVATE_OPERATOR"
        APPROVE_RULESET = "APPROVE_RULESET"
        BIND_RULESET = "BIND_RULESET"
        ACTIVATE_SEED_CHAIN = "ACTIVATE_SEED_CHAIN"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        CANCELLED = "CANCELLED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    action = models.CharField(max_length=32, choices=Action.choices)
    operator = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.PROTECT, related_name="approvals"
    )
    # What the request is about: operator public id, ruleset code, stream slug or chain id.
    subject = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    reason = models.TextField()
    requested_by = models.ForeignKey(
        PlatformStaff, on_delete=models.PROTECT, related_name="requests_made"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        PlatformStaff, null=True, blank=True, on_delete=models.PROTECT, related_name="decisions"
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["action", "subject"],
                condition=models.Q(status="PENDING"),
                name="uniq_pending_approval_subject",
            ),
            models.CheckConstraint(
                condition=models.Q(decided_by__isnull=True)
                | ~models.Q(decided_by=models.F("requested_by")),
                name="approver_is_not_requester",
            ),
        ]
