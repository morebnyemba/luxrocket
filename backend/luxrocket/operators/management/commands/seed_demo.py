"""Create a sandbox demo operator with an Ed25519 key pair (development only)."""

import base64
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core.management.base import BaseCommand
from django.db import transaction

from luxrocket.operators.models import (
    Market,
    Operator,
    OperatorCredential,
    OperatorCurrencyLimit,
    OperatorDomain,
    OperatorJurisdiction,
    WalletKind,
)

DEMO_COUNTRIES = ["ZW", "ZM", "BW", "ZA", "MZ", "MW", "NA"]


class Command(BaseCommand):
    help = "Seed a sandbox demo operator; writes its private key to --key-out (keep it local)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--key-out", default=".demo-operator.key")
        parser.add_argument("--origin", default="http://localhost:3000")
        parser.add_argument(
            "--wallet-url",
            default="",
            help="route the demo operator to a Seamless Wallet v1 endpoint (e.g. the simulator)",
        )

    @transaction.atomic
    def handle(self, *args: Any, **opts: Any) -> None:
        for code in DEMO_COUNTRIES:
            Market.objects.get_or_create(
                country_code=code, defaults={"status": Market.Status.SANDBOX}
            )
        operator, _ = Operator.objects.get_or_create(
            legal_name="Demo Sandbox Operator", defaults={"status": Operator.Status.SANDBOX}
        )
        if opts["wallet_url"]:
            operator.wallet_kind = WalletKind.SEAMLESS_V1
            operator.wallet_base_url = opts["wallet_url"]
        else:
            operator.wallet_kind = WalletKind.SIMULATED
        operator.save(update_fields=["wallet_kind", "wallet_base_url"])
        for code in DEMO_COUNTRIES:
            OperatorJurisdiction.objects.get_or_create(operator=operator, country_code=code)
        OperatorDomain.objects.get_or_create(operator=operator, origin=opts["origin"])
        OperatorCurrencyLimit.objects.get_or_create(
            operator=operator,
            currency="USD",
            defaults={
                "exponent": 2,
                "min_stake_minor": 10,
                "max_stake_minor": 10_000,
                "max_win_minor": 1_000_000,
                "round_exposure_limit_minor": 50_000_000,
            },
        )
        key = Ed25519PrivateKey.generate()
        n = OperatorCredential.objects.filter(operator=operator).count() + 1
        kid = f"k_demo_{operator.public_id[-8:]}_{n}"
        OperatorCredential.objects.create(
            operator=operator,
            kid=kid,
            public_key=key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        )
        raw = key.private_bytes_raw()
        Path(opts["key_out"]).write_text(f"{kid}\n{base64.b64encode(raw).decode()}\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"operator={operator.public_id} kid={kid} key written to {opts['key_out']}"
            )
        )
