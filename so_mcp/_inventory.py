"""
Inventory queries: read-only access to source_check_results, catalog_inventory
parquet files, and the inventory report.
"""

from __future__ import annotations

import json
from typing import Any

import _artifact
from lab_connectors.duckdb import gcs_connect


def query_inventory(
    source_id: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
    has_results: bool | None = None,
    grouped: bool = False,
) -> dict[str, Any]:
    """Query source_check_results.parquet with optional source and score filters.

    When ``grouped=True``, results are aggregated by ``dataset_group`` — one row
    per conceptual dataset instead of one per item.  Multi-year / multi-version
    items that share a ``dataset_group`` are collapsed into a single entry with
    aggregated year range and best intake score.
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

                if grouped and has_group_col:
                    # ── grouped mode: aggregate by dataset_group ──────────────
                    # Selected columns (use MAX for best values per group)
                    select_parts = [
                        "dataset_group",
                        "MIN(dataset_group_year_min) AS year_min",
                        "MAX(dataset_group_year_max) AS year_max",
                        "COUNT(*) AS item_count",
                        "MAX(intake_score) AS best_score",
                        # Source + best title from the group
                        "source_id",
                    ]
                    filters: list[str] = []
                    params: list[Any] = []

                    if source_id:
                        filters.append("source_id = ?")
                        params.append(source_id)
                    if min_score is not None:
                        filters.append("intake_score >= ?")
                        params.append(min_score)
                    if has_results is not None:
                        if has_results:
                            filters.append("intake_score IS NOT NULL AND intake_score > 0")
                        else:
                            filters.append("(intake_score IS NULL OR intake_score = 0)")
                    if not filters:
                        filters.append("1=1")

                    where = " AND ".join(filters)
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
                        "artifact": _artifact._display_path(_artifact._CHECK_PARQUET),
                        "cache": cache,
                        "gcs_uri": artifact.gcs_uri(),
                        "filters": {
                            "source_id": source_id,
                            "min_score": min_score,
                            "limit": safe_limit,
                            "has_results": has_results,
                            "grouped": True,
                        },
                        "warning": "dataset_group columns not available — run a fresh bulk_source_check to populate them",
                        "results": [],
                        "returned": 0,
                        "has_more": False,
                    }
                else:
                    # ── flat mode (original behavior) ─────────────────────────
                    query_parts = []
                    params = []

                    if source_id:
                        query_parts.append("source_id = ?")
                        params.append(source_id)
                    if min_score is not None:
                        query_parts.append("intake_score >= ?")
                        params.append(min_score)
                    if has_results is not None:
                        if has_results:
                            query_parts.append("intake_score IS NOT NULL AND intake_score > 0")
                        else:
                            query_parts.append("(intake_score IS NULL OR intake_score = 0)")

                    query = f'SELECT * FROM "{parquet_path}"'
                    if query_parts:
                        query += " WHERE " + " AND ".join(query_parts)
                    query += f" ORDER BY intake_score DESC NULLS LAST LIMIT {safe_limit}"

                    rows = con.execute(query, params).fetchall()
                    result_cols = cols

    except FileNotFoundError:
        return _artifact._parquet_not_found(artifact)

    result: dict[str, Any] = {
        "artifact": _artifact._display_path(_artifact._CHECK_PARQUET),
        "cache": cache,
        "gcs_uri": artifact.gcs_uri(),
        "filters": {
            "source_id": source_id,
            "min_score": min_score,
            "limit": safe_limit,
            "has_results": has_results,
            "grouped": bool(grouped),
        },
        "results": [dict(zip(result_cols, row)) for row in rows],
        "returned": len(rows),
        "has_more": len(rows) == safe_limit,
    }
    if grouped and has_group_col:
        result["grouped"] = True
        result["note"] = "Results are grouped by dataset_group — one row per conceptual dataset"
    return result


def inventory_status(source_id: str | None = None) -> dict[str, Any]:
    """Return catalog inventory build status from catalog_inventory_report.json."""
    loaded = _artifact._load_inventory_report()
    if loaded is None:
        return _artifact._json_not_found(_artifact._catalog_inventory_report_artifact())
    report, cache = loaded

    sources = report.get("sources", {})
    if not isinstance(sources, dict):
        sources = {}

    status_counts: dict[str, int] = {}
    rows_total = 0
    for info in sources.values():
        if not isinstance(info, dict):
            continue
        status = str(info.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        rows = info.get("rows")
        if isinstance(rows, int):
            rows_total += rows

    if source_id:
        source_info = sources.get(source_id)
        return {
            "artifact": _artifact._display_path(_artifact._INVENTORY_REPORT),
            "cache": cache,
            "captured_at": report.get("captured_at"),
            "filters": {"source_id": source_id},
            "source": source_info if isinstance(source_info, dict) else None,
            "returned": 1 if isinstance(source_info, dict) else 0,
        }

    compact_sources = []
    for key, info in sorted(sources.items()):
        if not isinstance(info, dict):
            continue
        compact_sources.append(
            {
                "source_id": key,
                "status": info.get("status"),
                "protocol": info.get("protocol"),
                "rows": info.get("rows"),
                "method": info.get("method"),
                "error": info.get("error"),
            }
        )

    return {
        "artifact": _artifact._display_path(_artifact._INVENTORY_REPORT),
        "cache": cache,
        "captured_at": report.get("captured_at"),
        "registry_path": report.get("registry_path"),
        "status_counts": status_counts,
        "rows_total": rows_total,
        "sources": compact_sources,
        "returned": len(compact_sources),
    }


def catalog_inventory_search(
    query: str,
    source_id: str | None = None,
    protocol: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Search catalog_inventory_latest.parquet across key text fields."""
    clean_query = (query or "").strip().lower()
    if not clean_query:
        return {"error": "empty_query", "message": "Provide a non-empty query."}

    safe_limit = max(1, min(int(limit or 25), 200))
    artifact = _artifact._catalog_inventory_parquet()
    try:
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            with gcs_connect(resolved_path) as con:
                columns = set(_artifact._table_columns(con, parquet_path))
                search_columns = [
                    column
                    for column in (
                        "item_id",
                        "item_name",
                        "title",
                        "tags",
                        "notes_excerpt",
                        "topic",
                        "theme",
                    )
                    if column in columns
                ]
                if not search_columns:
                    return {
                        "error": "schema_mismatch",
                        "message": "No searchable text columns found.",
                    }
                where = [
                    "("
                    + " OR ".join(
                        f"lower(coalesce(cast({column} as varchar), '')) LIKE ?"
                        for column in search_columns
                    )
                    + ")"
                ]
                like = f"%{clean_query}%"
                params: list[Any] = [like] * len(search_columns)
                if source_id:
                    where.append("source_id = ?")
                    params.append(source_id)
                if protocol:
                    where.append("protocol = ?")
                    params.append(protocol)

                select_columns = [
                    "source_id",
                    "protocol",
                    "item_id",
                    "item_name",
                    "title",
                    "organization",
                    "tags",
                    "landing_page",
                    "distribution_url",
                    "format",
                    "source_status",
                    "inventory_method",
                    "item_kind",
                    "api_base_url",
                    "captured_at",
                    "civic_priority",
                ]
                select_sql = ", ".join(
                    _artifact._select_expr(column, columns) for column in select_columns
                )
                sql = f"""
                    SELECT {select_sql}
                    FROM "{parquet_path}"
                    WHERE {" AND ".join(where)}
                    ORDER BY source_id NULLS LAST, title NULLS LAST, item_id
                    LIMIT {safe_limit}
                """
                rows = con.execute(sql, params).fetchall()
                cols = [desc[0] for desc in con.description]
    except FileNotFoundError:
        return _artifact._parquet_not_found(artifact)

    result: dict[str, Any] = {
        "artifact": _artifact._display_path(_artifact._INVENTORY_PARQUET),
        "cache": cache,
        "filters": {
            "query": clean_query,
            "source_id": source_id,
            "protocol": protocol,
            "limit": safe_limit,
        },
        "results": [dict(zip(cols, row)) for row in rows],
        "returned": len(rows),
        "has_more": len(rows) == safe_limit,
    }
    if not rows and source_id:
        result["source_status"] = _artifact._inventory_source_status(source_id)
    return result


def _source_radar_context(source_id: str) -> str | None:
    """Check radar_summary.json for source context (status, red_streak).

    Schema reale di radar_summary.json::

        {"sources": [{"id": "dati_salute", "status": "RED",
                      "red_streak": 14, ...}, ...]}
    """
    if not _artifact._RADAR_JSON.exists():
        return None
    try:
        with _artifact._RADAR_JSON.open(encoding="utf-8") as fh:
            radar = json.load(fh)
        sources_list = radar.get("sources") or []
        info = None
        for s in sources_list:
            if isinstance(s, dict) and s.get("id") == source_id:
                info = s
                break
        if not info:
            return None
        status = info.get("status", "unknown")
        red_streak = info.get("red_streak")
        if red_streak and status == "RED":
            return f"RED da {red_streak} giorni, inventories non generati"
        if status == "RED":
            return "RED (nessun inventory generato)"
        return f"status={status}"
    except Exception:
        return None


def inventory_diff(source_id: str) -> dict[str, Any]:
    """Compare current inventory against baseline for a source.

    Shows item count delta, baseline_date, and current_count.
    Uses catalog_inventory_latest.parquet + catalog_inventory_report.json.
    """
    if not source_id:
        return {"error": "invalid_params", "message": "source_id is required"}

    report_loaded = _artifact._load_inventory_report()
    if report_loaded is None:
        return {
            "error": "report_not_found",
            "message": "catalog_inventory_report.json not available",
            "source_id": source_id,
        }
    report, _cache = report_loaded

    source_info = (report.get("sources") or {}).get(source_id)
    if not source_info:
        radar_ctx = _source_radar_context(source_id)
        msg = f"source_id '{source_id}' not found in inventory report"
        if radar_ctx:
            msg += f". Radar: {radar_ctx}"
        return {
            "error": "source_not_in_report",
            "message": msg,
            "source_id": source_id,
            "radar_context": radar_ctx,
        }

    baseline = source_info.get("catalog_baseline", {})
    baseline_value = (
        baseline.get("value")
        or source_info.get("package_count")
        or source_info.get("dataflow_count")
        or source_info.get("rows")
    )
    baseline_date = baseline.get("captured_at") or source_info.get("last_inventory")

    try:
        artifact = _artifact._catalog_inventory_parquet()
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            with gcs_connect(resolved_path) as con:
                row = con.execute(
                    f'SELECT COUNT(*) FROM "{resolved_path}" WHERE source_id = ?',
                    [source_id],
                ).fetchone()
                current_count = row[0] if row else 0
    except FileNotFoundError:
        return _artifact._parquet_not_found(_artifact._catalog_inventory_parquet())

    delta = (current_count or 0) - (baseline_value or 0)

    notes: list[str] = []
    if not baseline_date:
        notes.append(
            "baseline_date non disponibile — report non contiene captured_at o last_inventory per questa fonte"
        )
    if not baseline_value:
        notes.append(
            "baseline_value non disponibile — delta non calcolabile; current_count è il primo inventario"
        )
    notes.append(
        "delta calcolato vs baseline nel registry; verificare se baseline_value è aggiornato"
    )

    return {
        "source_id": source_id,
        "baseline_date": baseline_date,
        "baseline_value": baseline_value,
        "current_count": current_count,
        "delta": delta,
        "delta_pct": round((delta / baseline_value * 100), 1) if baseline_value else None,
        "cache": cache,
        "note": " | ".join(notes),
    }
