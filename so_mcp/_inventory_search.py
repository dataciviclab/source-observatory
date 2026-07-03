"""
Inventory search: read-only access to catalog_inventory_latest.parquet.

Unifica:
- ``catalog_inventory_search`` (full-text search su inventory)
- ``list_source_items`` (item per fonte con paginazione)
- ``recommend_sources`` (raggruppa per fonte)
"""

from __future__ import annotations

from typing import Any

from lab_connectors.duckdb import gcs_connect

from . import _artifact


def inventory_search(
    query: str | None = None,
    source_id: str | None = None,
    protocol: str | None = None,
    keyword: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Cerca in catalog_inventory_latest.parquet.

    Modalità automatica in base ai parametri:

    * **keyword** → raggruppa per source_id (recommend mode)
    * **source_id** + no **query** → lista item con paginazione (list mode)
    * **query** → full-text search su title/item_name/tags (search mode)
    * **query** + **source_id** → search mode filtrato per fonte
    * **protocol** → filtro aggiuntivo in search mode
    """
    # Validazione parametri
    kw = (keyword or "").strip()
    q = (query or "").strip()
    sid = (source_id or "").strip()

    if not kw and not q and not sid:
        return {
            "error": "no_params",
            "message": "Provide at least one of: keyword, query, source_id.",
        }

    if kw and not q and not sid:
        return _recommend(kw, limit)
    if kw and q:
        # keyword + query: recommend con keyword, oppure search? prefer search
        return _search(q, source_id, protocol, limit)

    if sid and not q:
        return _list_items(sid, limit, offset)

    # Search mode: full-text (con o senza source_id/protocol)
    return _search(q, source_id, protocol, limit)


def _search(
    query: str,
    source_id: str | None = None,
    protocol: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Full-text search su catalog_inventory_latest.parquet."""
    clean_query = query.strip().lower()
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
                    col
                    for col in (
                        "item_id",
                        "item_name",
                        "title",
                        "tags",
                        "notes_excerpt",
                        "topic",
                        "theme",
                    )
                    if col in columns
                ]
                if not search_columns:
                    return {
                        "error": "schema_mismatch",
                        "message": "No searchable text columns found.",
                    }

                where = [
                    "("
                    + " OR ".join(
                        f"lower(coalesce(cast({col} as varchar), '')) LIKE ?"
                        for col in search_columns
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
                ]
                select_sql = ", ".join(
                    _artifact._select_expr(col, columns) for col in select_columns
                )
                sql = f"""
                    SELECT {select_sql}
                    FROM "{parquet_path}"
                    WHERE {" AND ".join(where)}
                    ORDER BY source_id NULLS LAST, title NULLS LAST, item_id
                    LIMIT {safe_limit}
                """
                rows = con.execute(sql, params).fetchall()
                result_cols = [desc[0] for desc in con.description]
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
        "results": [dict(zip(result_cols, row)) for row in rows],
        "returned": len(rows),
        "has_more": len(rows) == safe_limit,
    }
    if not rows and source_id:
        result["source_status"] = _artifact._inventory_source_status(source_id)
    return result


def _list_items(
    source_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Elenca gli item di una fonte con paginazione."""
    if not source_id or not str(source_id).strip():
        return {"error": "invalid_params", "message": "source_id is required"}

    safe_limit = max(1, min(int(limit or 50), 500))
    safe_offset = max(0, int(offset or 0))

    artifact = _artifact._catalog_inventory_parquet()
    try:
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            with gcs_connect(resolved_path) as con:
                columns = set(_artifact._table_columns(con, parquet_path))

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
                ]
                select_sql = ", ".join(
                    _artifact._select_expr(col, columns) for col in select_columns
                )

                where_parts = ["source_id = ?"]
                params: list[Any] = [source_id]

                where = " AND ".join(where_parts)

                count_row = con.execute(
                    f'SELECT COUNT(*) FROM "{parquet_path}" WHERE {where}',
                    params,
                ).fetchone()
                total_count = count_row[0] if count_row else 0

                sql = f"""
                    SELECT {select_sql}
                    FROM "{parquet_path}"
                    WHERE {where}
                    ORDER BY title NULLS LAST, item_id
                    LIMIT {safe_limit} OFFSET {safe_offset}
                """
                rows = con.execute(sql, params).fetchall()
                result_cols = [desc[0] for desc in con.description]

    except FileNotFoundError:
        return _artifact._parquet_not_found(artifact)

    returned = len(rows)
    result: dict[str, Any] = {
        "artifact": _artifact._display_path(_artifact._INVENTORY_PARQUET),
        "cache": cache,
        "gcs_uri": artifact.gcs_uri(),
        "source_id": source_id,
        "filters": {
            "limit": safe_limit,
            "offset": safe_offset,
        },
        "total_count": total_count,
        "results": [dict(zip(result_cols, row)) for row in rows],
        "returned": returned,
        "has_more": (safe_offset + returned) < total_count,
    }
    if not rows:
        result["source_status"] = _artifact._inventory_source_status(source_id)
        result["note"] = (
            "Nessun item trovato. Verifica che source_id sia corretto "
            "e che l'inventory sia stato buildato di recente."
        )
    return result


def _recommend(keyword: str, limit: int = 10) -> dict[str, Any]:
    """Raggruppa item per fonte (recommend mode)."""
    if not keyword or not str(keyword).strip():
        return {"error": "empty_keyword", "message": "Provide non-empty keyword."}

    safe_limit = max(1, min(int(limit or 10), 50))
    keyword_low = str(keyword).strip().lower()

    try:
        artifact = _artifact._catalog_inventory_parquet()
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            with gcs_connect(resolved_path) as con:
                total_row = con.execute(f'SELECT COUNT(*) FROM "{resolved_path}"').fetchone()
                total_items = total_row[0] if total_row else 0

                rows = con.execute(
                    f"""
                    SELECT source_id, source_kind, protocol,
                           COUNT(*) as item_count,
                           STRING_AGG(DISTINCT organization, ', ') as organizations
                    FROM "{resolved_path}"
                    WHERE (
                        LOWER(item_name) LIKE ? OR
                        LOWER(title) LIKE ? OR
                        LOWER(tags) LIKE ? OR
                        LOWER(organization) LIKE ? OR
                        LOWER(notes_excerpt) LIKE ?
                    )
                    GROUP BY source_id, source_kind, protocol
                    ORDER BY item_count DESC
                    LIMIT ?
                    """,
                    [f"%{keyword_low}%"] * 5 + [safe_limit],
                ).fetchall()
    except FileNotFoundError:
        return _artifact._parquet_not_found(_artifact._catalog_inventory_parquet())

    cols = ["source_id", "source_kind", "protocol", "item_count", "organizations"]
    sources = [dict(zip(cols, row)) for row in rows]

    return {
        "keyword": keyword.strip(),
        "filters": {"limit": safe_limit},
        "sources": sources,
        "returned": len(sources),
        "total_items_in_inventory": total_items,
        "cache": cache,
    }
