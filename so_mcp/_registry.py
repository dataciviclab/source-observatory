"""Registry queries: read-only access to sources_registry.yaml."""

from __future__ import annotations

from typing import Any

import _artifact


def registry_query(
    protocol: str | None = None,
    source_kind: str | None = None,
    observation_mode: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Query sources_registry.yaml with optional filters."""
    if not _artifact._REGISTRY_YAML.exists():
        return _artifact._artifact_not_found(_artifact._REGISTRY_YAML, "sources_registry.yaml")

    import yaml

    with _artifact._REGISTRY_YAML.open(encoding="utf-8") as fh:
        registry = yaml.safe_load(fh)

    if not isinstance(registry, dict):
        return {"error": "invalid_registry", "message": "Registry is not a dict."}

    results = []
    for sid, info in sorted(registry.items()):
        if source_id and sid != source_id:
            continue
        if source_kind and info.get("source_kind") != source_kind:
            continue
        if protocol and info.get("protocol") != protocol:
            continue
        if observation_mode and info.get("observation_mode") != observation_mode:
            continue
        results.append(
            {
                "source_id": sid,
                "source_kind": info.get("source_kind"),
                "protocol": info.get("protocol"),
                "observation_mode": info.get("observation_mode"),
                "base_url": info.get("base_url"),
                "verdict": info.get("verdict"),
                "last_probed": info.get("last_probed"),
                "datasets_in_use": info.get("datasets_in_use", []),
                "note": info.get("note"),
            }
        )

    return {
        "artifact": _artifact._display_path(_artifact._REGISTRY_YAML),
        "filters": {
            "source_id": source_id,
            "protocol": protocol,
            "source_kind": source_kind,
            "observation_mode": observation_mode,
        },
        "results": results,
        "returned": len(results),
    }
