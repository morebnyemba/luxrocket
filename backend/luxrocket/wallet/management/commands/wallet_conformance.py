"""Run the Seamless Wallet v1 conformance suite against an operator's wallet endpoints."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from luxrocket.operators.models import Operator
from luxrocket.wallet import conformance


class Command(BaseCommand):
    help = "Exercise an operator wallet (debit/credit/rollback semantics, doc 09 §6.5)."

    def add_arguments(self, parser: Any) -> None:
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--operator", help="operator public id (uses its wallet_base_url)")
        target.add_argument("--base-url", help="wallet base URL")
        parser.add_argument("--player-id", required=True, help="a dedicated TEST player")
        parser.add_argument("--currency", default="USD")
        parser.add_argument("--stake", type=int, default=100)

    def handle(self, *args: Any, **opts: Any) -> None:
        base_url = opts["base_url"]
        if opts["operator"]:
            op = Operator.objects.filter(public_id=opts["operator"]).first()
            if op is None or not op.wallet_base_url:
                raise CommandError("unknown operator or no wallet_base_url configured")
            base_url = op.wallet_base_url
        report = conformance.run(
            base_url, player_id=opts["player_id"], currency=opts["currency"], stake=opts["stake"]
        )
        self.stdout.write(report.as_text())
        if not report.passed:
            raise CommandError("wallet is not conformant")
