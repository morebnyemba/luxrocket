"""WebAuthn ceremonies for platform staff (doc 15 T-14: phishing-resistant MFA).

Challenges are bound to the staff session, expire after 5 minutes and are consumed by the first
verification attempt. User verification (PIN/biometric on the key) is required.
"""

import hashlib
import json
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from luxrocket.console.models import Passkey, PlatformSession, PlatformStaff

CHALLENGE_TTL = timedelta(minutes=5)
RP_NAME = "LUX ROCKET Platform"


class PasskeyError(Exception):
    pass


def credential_hash(raw_id: bytes) -> str:
    return hashlib.sha256(raw_id).hexdigest()


def _remember(session: PlatformSession, challenge: bytes, kind: str) -> None:
    session.challenge = challenge
    session.challenge_kind = kind
    session.challenge_expires_at = timezone.now() + CHALLENGE_TTL
    session.save(update_fields=["challenge", "challenge_kind", "challenge_expires_at"])


def _consume(session: PlatformSession, kind: str) -> bytes:
    """Single use: cleared before verification, whatever the outcome."""
    challenge = bytes(session.challenge) if session.challenge else b""
    valid = (
        challenge
        and session.challenge_kind == kind
        and session.challenge_expires_at is not None
        and session.challenge_expires_at > timezone.now()
    )
    PlatformSession.objects.filter(pk=session.pk).update(
        challenge=None, challenge_kind="", challenge_expires_at=None
    )
    if not valid:
        raise PasskeyError("CHALLENGE_EXPIRED")
    return challenge


def _descriptors(staff: PlatformStaff) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(id=bytes(p.credential_id))
        for p in Passkey.objects.filter(staff=staff)
    ]


def registration_options(session: PlatformSession) -> dict[str, Any]:
    staff = session.staff
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=RP_NAME,
        user_id=bytes(staff.webauthn_user_id),
        user_name=staff.email,
        user_display_name=staff.email,
        exclude_credentials=_descriptors(staff),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _remember(session, options.challenge, "register")
    out: dict[str, Any] = json.loads(options_to_json(options))
    return out


def register(session: PlatformSession, credential: dict[str, Any], name: str) -> Passkey:
    challenge = _consume(session, "register")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGINS,
            require_user_verification=True,
        )
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError) as exc:
        raise PasskeyError("PASSKEY_INVALID") from exc
    raw_id = verified.credential_id
    if Passkey.objects.filter(credential_id_hash=credential_hash(raw_id)).exists():
        raise PasskeyError("PASSKEY_ALREADY_REGISTERED")
    return Passkey.objects.create(
        staff=session.staff,
        credential_id=raw_id,
        credential_id_hash=credential_hash(raw_id),
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        name=name[:60],
    )


def authentication_options(session: PlatformSession) -> dict[str, Any]:
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=_descriptors(session.staff),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _remember(session, options.challenge, "assert")
    out: dict[str, Any] = json.loads(options_to_json(options))
    return out


def authenticate(session: PlatformSession, credential: dict[str, Any]) -> Passkey:
    challenge = _consume(session, "assert")
    from webauthn import base64url_to_bytes

    try:
        raw_id = base64url_to_bytes(str(credential.get("rawId") or credential.get("id", "")))
    except ValueError as exc:
        raise PasskeyError("PASSKEY_INVALID") from exc
    passkey = Passkey.objects.filter(
        staff=session.staff, credential_id_hash=credential_hash(raw_id)
    ).first()
    if passkey is None:
        raise PasskeyError("PASSKEY_INVALID")
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGINS,
            credential_public_key=bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError) as exc:
        raise PasskeyError("PASSKEY_INVALID") from exc
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])
    return passkey
