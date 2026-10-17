from typing import Any

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _apply_tenancy(**kwargs: Any) -> None:
    from luxrocket.core import tenancy

    tenancy.apply()


class PortalConfig(AppConfig):
    name = "luxrocket.portal"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # After every migrate: keep row-level security and portal grants in sync with
        # luxrocket.core.tenancy (new tables, changed classification).
        post_migrate.connect(_apply_tenancy, sender=self, dispatch_uid="lr_tenancy")
