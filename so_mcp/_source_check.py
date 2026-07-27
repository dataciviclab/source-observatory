"""
Source-check queries: read-only access to validated.parquet
and inventory status/diff from catalog_inventory_report.json.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from lab_connectors.duckdb import gcs_connect

from . import _artifact

logger = logging.getLogger("so_mcp._source_check")


def query_inventory(
    source_id: str | None = None,
    min_score: int | None = None,
    min_paqa_score: int | None = None,  # noqa: ARG001 — kept for backward compat
    limit: int = 50,
    has_results: bool | None = None,
    grouped: bool = False,
) -> dict[str, Any]:
    """Query validated.parquet with optional source and score filters.

    ``min_paqa_score`` is accepted for backward compatibility but ignored
    (paqa_score non e' piu' calcolato nella nuova pipeline).

    When ``grouped=True``, results are aggregated by ``dataset_group``.
    """
    safe_limit = max(1, min(int(limit or 50), 200))
    artifact = _artifact._source_check_parquet()
    try:
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            with gcs_connect(resolved_path) as con:
                cols = _artifact._table_columns(con, parquet_path)
                col_set = set(cols)
                has_group_col = "dataset_group" in col_set
                has_readiness = "readiness_score" in col_set

                if grouped and has_group_col:
                    # ── grouped mode: aggregate by dataset_group ──────────────
                    select_parts = [
                        "dataset_group",
                        "source_id",
                        "MAX(readiness_score) AS best_score",
                        "MIN(item_count) AS item_count",
                    ]
                    if "num_columns" in col_set:
                        select_parts.append("MAX(num_columns) AS max_columns")
                    filters: list[str] = []
                    params: list[Any] = []

                    if source_id:
                        filters.append("source_id = ?")
                        params.append(source_id)
                    if min_score is not None and has_readiness:
                        filters.append("readiness_score >= ?")
                        params.append(min_score)
                    if has_results is not None:
                        if has_results:
                            filters.append("reachable = true")
                        else:
                            filters.append("(reachable IS NULL OR reachable = false)")

                    where = " AND ".join(filters) if filters else "1=1"
                    query = (
                        f"SELECT {', '.join(select_parts)} "
                        f'FROM "{parquet_path}" '
                        f"WHERE {where} "
                        f"GROUP BY dataset_group, source_id "
                        f"ORDER BY best_score DESC NULLS LAST "
                        f"LIMIT {safe_limit}"
                    )
                    rows = con.execute(query, params).fetchall()
                    result_cols = [desc[0] for desc in con.description]
                elif grouped and not has_group_col:
                    return {
                        "artifact": _artifact._display_path(_artifact._VALIDATED_PARQUET),
                        "cache": cache,
                        "gcs_uri": artifact.gcs_uri(),
                        "filters": {
                            "source_id": source_id,
                            "min_score": min_score,
                            "limit": safe_limit,
                            "has_results": has_results,
                            "grouped": grouped,
                        },
                        "results": [],
                        "warning": "dataset_group column not available — run merge first",
                    }
                else:
                    # ── flat mode: one row per group ────────────────────────────
                    filters = ["1=1"]
                    params = []
                    if source_id:
                        filters = ["source_id = ?"]
                        params = [source_id]
                    if min_score is not None and has_readiness:
                        filters.append("readiness_score >= ?")
                        params.append(min_score)
                    if has_results is not None:
                        if has_results:
                            filters.append("reachable = true")
                        else:
                            filters.append("(reachable IS NULL OR reachable = false)")

                    where = " AND ".join(filters)
                    query = (
                        f"SELECT * "
                        f'FROM "{parquet_path}" '
                        f"WHERE {where} "
                        f"ORDER BY readiness_score DESC NULLS LAST "
                        f"LIMIT {safe_limit}"
                    )
                    rows = con.execute(query, params).fetchall()
                    result_cols = [desc[0] for desc in con.description]

                results = [dict(zip(result_cols, row)) for row in rows]

                return {
                    "artifact": _artifact._display_path(_artifact._VALIDATED_PARQUET),
                    "cache": cache,
                    "gcs_uri": artifact.gcs_uri(),
                    "filters": {
                        "source_id": source_id,
                        "min_score": min_score,
                        "limit": safe_limit,
                        "has_results": has_results,
                        "grouped": grouped,
                    },
                    "results": results,
                    "returned": len(results),
                    "has_more": len(results) >= safe_limit,
                }
    except Exception as exc:
        return {
            "artifact": _artifact._display_path(_artifact._VALIDATED_PARQUET),
            "filters": {
                "source_id": source_id,
                "min_score": min_score,
                "limit": safe_limit,
                "has_results": has_results,
            },
            "results": [],
            "error": str(exc),
        }


def inventory_status(source_id: str | None = None) -> dict[str, Any]:
    """Inventory status from catalog_inventory_report.json."""
    path = _artifact._INVENTORY_REPORT
    if not path.exists():
        return {"error": "catalog_inventory_report.json non trovato"}
    try:
        data = json.loads(path.read_text())
        sources = data.get("sources", [])
        if source_id:
            sources = [s for s in sources if s.get("source_id") == source_id]
            if not sources:
                return {"error": f"Source '{source_id}' non trovato"}
        return {"sources": sources, "captured_at": data.get("captured_at")}
    except Exception as exc:
        return {"error": str(exc)}


def _source_radar_context(source_id: str) -> str | None:
    """Build radar context string for a source."""
    try:
        radar = json.loads(_artifact._RADAR_JSON.read_text())
        entry = radar.get("sources", {}).get(source_id)
        if entry:
            status = entry.get("status", "?")
            http = entry.get("http_code", "?")
            return f"radar={status} http={http}"
    except Exception:
        pass
    return None


def inventory_diff(source_id: str) -> dict[str, Any]:
    """Inventory diff from catalog_inventory_report.json."""
    status = inventory_status(source_id)
    if "error" in status:
        return status

    path = _artifact._INVENTORY_REPORT
    data = json.loads(path.read_text())
    total = 0
    delta: int | None = None
    for s in data.get("sources", []):
        if s.get("source_id") == source_id:
            total = s.get("total", 0)
            delta = s.get("since_last")
            break

    return {
        "source_id": source_id,
        "inventory_total": total,
        "delta_since_last": delta,
        "radar_context": _source_radar_context(source_id),
    }
