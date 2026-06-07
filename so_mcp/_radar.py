"""Radar queries: read-only access to radar_summary.json, radar_history.json, STATUS.md."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import _artifact


def radar_summary(source_id: str | None = None) -> dict[str, Any]:
    """Return radar health summary, optionally for one source."""
    if not _artifact._RADAR_JSON.exists():
        return _artifact._artifact_not_found(_artifact._RADAR_JSON, "radar_summary.json")

    with _artifact._RADAR_JSON.open(encoding="utf-8") as fh:
        radar_doc = json.load(fh)

    sources = radar_doc.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    if source_id:
        sources = [source for source in sources if source.get("id") == source_id]

    return {
        "artifact": _artifact._display_path(_artifact._RADAR_JSON),
        "generated_at": radar_doc.get("generated_at"),
        "probe_date": radar_doc.get("probe_date"),
        "sources_total": radar_doc.get("sources_total"),
        "status_counts": radar_doc.get("status_counts", {}),
        "persistent_red": radar_doc.get("persistent_red"),
        "filters": {"source_id": source_id},
        "sources": sources,
        "returned": len(sources),
    }


def radar_history(source_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    """Return radar_history.json: probe history per fonte."""
    if not _artifact._RADAR_HISTORY_JSON.exists():
        return _artifact._artifact_not_found(_artifact._RADAR_HISTORY_JSON, "radar_history.json")

    with _artifact._RADAR_HISTORY_JSON.open(encoding="utf-8") as fh:
        history_doc = json.load(fh)

    probes = history_doc.get("probes", [])
    if not isinstance(probes, list):
        probes = []

    safe_limit = max(1, min(int(limit or 5), 20))
    recent_probes = list(reversed(probes))[-safe_limit:] if probes else []

    sources_map: dict[str, list[dict[str, Any]]] = {}
    for probe in recent_probes:
        for src in probe.get("sources", []):
            sid = src.get("id", "unknown")
            if source_id and sid != source_id:
                continue
            if sid not in sources_map:
                sources_map[sid] = []
            sources_map[sid].append(
                {
                    "probe_date": probe.get("probe_date"),
                    "status": src.get("status"),
                    "http_code": src.get("http_code"),
                    "note": src.get("note"),
                }
            )

    results = []
    for sid, entries in sorted(sources_map.items()):
        entries.sort(key=lambda e: e.get("probe_date") or "", reverse=True)
        red_count = sum(1 for e in entries if e.get("status") == "RED")
        results.append(
            {
                "source_id": sid,
                "probes": entries,
                "recent_red_count": red_count,
                "current_status": entries[0].get("status") if entries else None,
            }
        )

    return {
        "artifact": _artifact._display_path(_artifact._RADAR_HISTORY_JSON),
        "captured_at": history_doc.get("captured_at"),
        "filters": {"source_id": source_id, "limit": safe_limit},
        "sources": results,
        "returned": len(results),
        "probes_in_window": len(recent_probes),
    }


def radar_status_md() -> dict[str, Any]:
    """Return STATUS.md content as plain text for human-readable radar state."""
    if not _artifact._STATUS_MD.exists():
        return _artifact._artifact_not_found(_artifact._STATUS_MD, "STATUS.md")

    content = _artifact._STATUS_MD.read_text(encoding="utf-8")
    stat = _artifact._STATUS_MD.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    age_hours = (datetime.now(timezone.utc) - modified_at).total_seconds() / 3600

    return {
        "artifact": _artifact._display_path(_artifact._STATUS_MD),
        "modified_at": modified_at.isoformat(),
        "age_hours": round(age_hours, 2),
        "content": content,
    }
