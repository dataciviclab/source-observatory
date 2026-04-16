from __future__ import annotations

from typing import Any
from .base import CollectorResult
from . import ckan, sdmx, sparql

COLLECTORS = {
    "ckan": ckan.collect,
    "sdmx": sdmx.collect,
    "sparql": sparql.collect,
}


def supported_protocols() -> set[str]:
    return set(COLLECTORS.keys())


def dispatch(source_id: str, source_cfg: dict[str, Any], captured_at: str) -> CollectorResult:
    protocol = source_cfg.get("protocol")
    collector = COLLECTORS.get(protocol)
    if not collector:
        raise ValueError(f"Unsupported protocol for catalog inventory: {protocol}")
    return collector(source_id, source_cfg, captured_at)
