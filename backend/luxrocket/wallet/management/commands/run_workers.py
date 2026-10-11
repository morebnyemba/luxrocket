"""Background loop: wallet credits/rollbacks and the outbox relay (doc 02 §3 process types)."""

import logging
import signal
import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from luxrocket.operators.signing import prune_nonces
from luxrocket.operators.webhooks import deliver_due
from luxrocket.wallet import reconciliation, worker
from luxrocket.wallet.outbox import relay_once

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the wallet worker, outbox relay, webhooks and reconciliation until stopped."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--interval", type=float, default=0.2)

    def handle(self, *args: Any, **opts: Any) -> None:
        running = True

        def stop(*_: object) -> None:
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        last_prune = 0.0
        last_internal = 0.0
        last_operator = 0.0
        self.stdout.write("workers running")
        while running:
            close_old_connections()
            try:
                worker.process_pending()
                while relay_once():
                    pass
                deliver_due()
                if time.monotonic() - last_prune > 60:
                    prune_nonces()
                    last_prune = time.monotonic()
                if time.monotonic() - last_internal > settings.RECON_INTERNAL_INTERVAL_S:
                    last_internal = time.monotonic()
                    reconciliation.run_internal()
                if time.monotonic() - last_operator > settings.RECON_OPERATOR_INTERVAL_S:
                    last_operator = time.monotonic()
                    reconciliation.run_all_operators()
            except Exception:
                log.exception("worker iteration failed")
            time.sleep(opts["interval"])
