"""Bootstrap the single PLAT_OWNER (doc 12 §4). Refuses if an owner already exists."""

import os
import secrets
from typing import Any

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from luxrocket.console.models import PlatformStaff, Role
from luxrocket.portal import audit


class Command(BaseCommand):
    help = "Create the platform owner. They must enrol a passkey at first sign-in."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", help="known password (development only)")
        parser.add_argument(
            "--role",
            default=Role.OWNER,
            choices=Role.values,
            help="development/testing: create another role instead",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        role = opts["role"]
        if role == Role.OWNER and PlatformStaff.objects.filter(role=Role.OWNER).exists():
            raise CommandError("an owner already exists (exactly one is allowed)")
        email = opts["email"].strip().lower()
        if PlatformStaff.objects.filter(email=email).exists():
            raise CommandError("that email already exists")
        password = opts["password"] or secrets.token_urlsafe(14)
        PlatformStaff.objects.create(
            email=email,
            role=role,
            password_hash=make_password(password),
            must_change_password=not opts["password"],
            webauthn_user_id=os.urandom(32),
        )
        audit.record(
            realm="PLATFORM",
            actor="manage.py",
            action="staff.created",
            target=email,
            data={"role": role},
        )
        self.stdout.write(f"{email} ({role}) created; passkey enrolment required at first sign-in")
        if not opts["password"]:
            self.stdout.write(f"temporary password (shown once): {password}")
