"""Run reconciliation now (the workers also run it on a schedule)."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from luxrocket.operators.models import Operator
from luxrocket.wallet import reconciliation
from luxrocket.wallet.models import Discrepancy


class Command(BaseCommand):
    help = "Internal and/or operator reconciliation (doc 08 §8). Exit 1 if items are open."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--internal", action="store_true")
        parser.add_argument("--operator", help="operator public id, or 'all'")

    def handle(self, *args: Any, **opts: Any) -> None:
        runs = []
        if opts["internal"] or not opts["operator"]:
            runs.append(reconciliation.run_internal())
        if opts["operator"] == "all":
            runs += reconciliation.run_all_operators()
        elif opts["operator"]:
            op = Operator.objects.filter(public_id=opts["operator"]).first()
            if op is None:
                raise CommandError("unknown operator")
            runs.append(reconciliation.run_operator(op))
        for r in runs:
            who = r.operator.public_id if r.operator else "platform"
            self.stdout.write(
                f"{r.kind:<8} {who:<32} {r.status:<11} checked={r.checked} "
                f"opened={r.opened} auto_resolved={r.auto_resolved} {r.note}"
            )
        still_open = Discrepancy.objects.filter(status=Discrepancy.Status.OPEN).count()
        self.stdout.write(f"open discrepancies: {still_open}")
        if still_open or any(r.status != "COMPLETED" for r in runs):
            raise CommandError("reconciliation found open items or could not complete")
