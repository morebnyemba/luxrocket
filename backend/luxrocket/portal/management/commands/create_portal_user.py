"""Bootstrap an operator portal user (the first OP_OWNER); prints a one-time password."""

import secrets
from typing import Any

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from luxrocket.operators.models import Operator
from luxrocket.portal import audit
from luxrocket.portal.models import Role, StaffUser


class Command(BaseCommand):
    help = "Create a portal user for an operator. The temporary password is shown once."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--operator", required=True, help="operator public id or legal name")
        parser.add_argument("--email", required=True)
        parser.add_argument("--role", default=Role.OWNER, choices=Role.values)
        parser.add_argument("--password", help="set a known password (development only)")

    def handle(self, *args: Any, **opts: Any) -> None:
        ref = opts["operator"]
        op = (
            Operator.objects.filter(public_id=ref).first()
            or Operator.objects.filter(legal_name=ref).first()
        )
        if op is None:
            raise CommandError("unknown operator")
        email = opts["email"].strip().lower()
        password = opts["password"] or secrets.token_urlsafe(12)
        _, created = StaffUser.objects.update_or_create(
            email=email,
            defaults={
                "operator": op,
                "role": opts["role"],
                "password_hash": make_password(password),
                "must_change_password": not opts["password"],
                "status": StaffUser.Status.ACTIVE,
            },
        )
        audit.record(
            realm="PLATFORM",
            actor="manage.py",
            action="user.created" if created else "user.reset",
            operator_id=op.pk,
            target=email,
            data={"role": opts["role"]},
        )
        self.stdout.write(f"{email} ({opts['role']}) for {op.public_id}")
        if not opts["password"]:
            self.stdout.write(f"temporary password (shown once): {password}")
