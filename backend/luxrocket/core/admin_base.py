"""Interim back-office (Django admin) until the platform admin console ships (Phase F).

Financial and round records are strictly read-only here: no add, change or delete (FR-034).
"""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest


class ReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
