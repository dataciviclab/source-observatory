"""
SO MCP core — readonly artifact queries.

Artifact paths resolved relative to this package (source-observatory/).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHECK_PARQUET = _REPO_ROOT / "data" / "catalog_inventory" / "generated" / "source_check_results.parquet"
_SIGNALS_JSON = _REPO_ROOT / "data" / "catalog" / "catalog_signals.json"


def query_inventory(
    source_id: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Query source_check_results.parquet with optional filters.

    Args:
        source_id: filter to exact source_id (e.g. 'inps', 'istat_sdmx')
        min_score: filter rows with intake_score >= min_score
        limit: max rows returned (default 50)

    Returns:
        dict with artifact path, filters, results list, returned count, has_more.
        Results columns: source_id, item_id, reachable, http_status, granularity,
        year_min, year_max, intake_score, intake_candidate.
    """
    if not _CHECK_PARQUET.exists():
        return {
            "error": "artifact_not_found",
            "message": f"source_check_results.parquet not found at {_CHECK_PARQUET}",
            "hint": "Run: python -m mcp.so_server from source-observatory/ to initialize",
        }

    parquet_path = str(_CHECK_PARQUET.resolve())
    con = duckdb.connect()

    query = f'SELECT * FROM "{parquet_path}"'
    filters: list[str] = []
    params: list[Any] = []

    if source_id:
        filters.append("source_id = ?")
        params.append(source_id)
    if min_score is not None:
        filters.append("intake_score >= ?")
        params.append(min_score)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += f" ORDER BY intake_score DESC NULLS LAST LIMIT {limit}"

    try:
        rows = con.execute(query, params).fetchall()
        cols = [c[0] for c in con.execute(f'DESCRIBE FROM "{parquet_path}"').fetchall()]
        results = [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}
    finally:
        con.close()

    return {
        "artifact": str(_CHECK_PARQUET.relative_to(_REPO_ROOT)),
        "filters": {"source_id": source_id, "min_score": min_score, "limit": limit},
        "results": results,
        "returned": len(results),
        "has_more": len(results) == limit,
    }


def query_signals(
    source_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Query catalog_signals.json with optional filters.

    Args:
        source_id: filter to exact source (e.g. 'opencoesione')
        limit: if provided, return only the last N signals per source

    Returns:
        dict with artifact path, captured_at, filters, signals list.
        Each signal: source, protocol, signal_type, result, detail, suggested_action.
        When limit is set, returns the last N signals (globally, not per source).
    """
    if not _SIGNALS_JSON.exists():
        return {
            "error": "artifact_not_found",
            "message": f"catalog_signals.json not found at {_SIGNALS_JSON}",
        }

    with _SIGNALS_JSON.open(encoding="utf-8") as f:
        signals_doc = json.load(f)

    signals = signals_doc.get("signals", [])
    if source_id:
        signals = [s for s in signals if s.get("source") == source_id]

    return {
        "artifact": str(_SIGNALS_JSON.relative_to(_REPO_ROOT)),
        "captured_at": signals_doc.get("captured_at", ""),
        "filters": {"source_id": source_id, "limit": limit},
        "signals": signals[-limit:] if limit is not None else signals,
        "returned": len(signals[-limit:] if limit is not None else signals),
    }
