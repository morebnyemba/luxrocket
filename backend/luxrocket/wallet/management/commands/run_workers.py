"""Background loop: wallet credits/rollbacks and the outbox relay (doc 02 §3 process types)."""

import logging
import signal
import time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from luxrocket.operators.signing import prune_nonces
from luxrocket.wallet import worker
from luxrocket.wallet.outbox import relay_once

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the wallet worker and outbox relay until stopped."

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
        self.stdout.write("workers running")
        while running:
            close_old_connections()
            try:
                worker.process_pending()
                while relay_once():
                    pass
                if time.monotonic() - last_prune > 60:
                    prune_nonces()
                    last_prune = time.monotonic()
            except Exception:
                log.exception("worker iteration failed")
            time.sleep(opts["interval"])
