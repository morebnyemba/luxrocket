"""Ruleset bindings: the desired state Phoenix adopts at the next round boundary (doc 12 §3.3)."""

from typing import Any

from django.db import transaction

from luxrocket.gaming.models import GameRuleset, StreamConfig
from luxrocket.wallet.outbox import emit


def config_view(config: StreamConfig) -> dict[str, Any]:
    rs = config.ruleset
    return {
        "stream": config.stream_slug,
        "version": config.version,
        "ruleset": {
            "code": rs.code,
            "house_edge_bp": rs.house_edge_bp,
            "max_multiplier_x10000": rs.max_multiplier_x10000,
        },
    }


def bind(stream: str, ruleset: GameRuleset) -> StreamConfig:
    """Point a stream at an approved ruleset and tell Phoenix (outbox, same transaction)."""
    if ruleset.status != GameRuleset.Status.APPROVED:
        raise ValueError("only approved rulesets can be bound")
    with transaction.atomic():
        config = StreamConfig.objects.select_for_update().filter(stream_slug=stream).first()
        if config is None:
            config = StreamConfig.objects.create(stream_slug=stream, ruleset=ruleset, version=1)
        else:
            config.ruleset = ruleset
            config.version += 1
            config.save(update_fields=["ruleset", "version", "updated_at"])
        emit("stream.config", config_view(config))
    return config
