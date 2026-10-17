"""Exit non-zero if any money-correctness invariant is violated."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from luxrocket.gaming import invariants


class Command(BaseCommand):
    help = "Check ledger, settlement and outcome invariants."

    def handle(self, *args: Any, **opts: Any) -> None:
        failed = 0
        for name, violations in invariants.run():
            mark = "OK  " if violations == 0 else "FAIL"
            self.stdout.write(f"{mark} {name}" + (f" ({violations})" if violations else ""))
            failed += violations > 0
        if failed:
            raise CommandError(f"{failed} invariant(s) violated")
