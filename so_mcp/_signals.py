"""Catalog signals: read-only query of catalog_signals.json."""

from __future__ import annotations

import json
from typing import Any

from . import _artifact


def query_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Query catalog_signals.json with optional source filter."""
    if not _artifact._SIGNALS_JSON.exists():
        return _artifact._artifact_not_found(_artifact._SIGNALS_JSON, "catalog_signals.json")

    with _artifact._SIGNALS_JSON.open(encoding="utf-8") as fh:
        signals_doc = json.load(fh)

    signals = signals_doc.get("signals", [])
    if source_id:
        signals = [signal for signal in signals if signal.get("source") == source_id]

    safe_limit = None if limit is None else max(1, min(int(limit), 200))
    selected = signals[-safe_limit:] if safe_limit is not None else signals
    return {
        "artifact": _artifact._display_path(_artifact._SIGNALS_JSON),
        "captured_at": signals_doc.get("captured_at", ""),
        "filters": {"source_id": source_id, "limit": safe_limit},
        "signals": selected,
        "returned": len(selected),
    }
