"""
Discovery: elenca gli item di una fonte dal catalog_inventory_latest.parquet.

``list_source_items(source_id)`` restituisce la lista degli item (dataset,
dataflow, risorsa) enumerati dall'ultimo build inventory per quella fonte,
con paginazione e filtro testuale opzionale.
"""

from __future__ import annotations

from typing import Any

import _artifact
from lab_connectors.duckdb import safe_connect


def list_source_items(
    source_id: str,
    limit: int = 50,
    offset: int = 0,
    query: str | None = None,
) -> dict[str, Any]:
    """Elenca gli item di una fonte dal catalog_inventory_latest.parquet.

    Args:
        source_id: Identificativo della fonte (es. ``inps``, ``istat_sdmx``).
        limit: Numero massimo di item da restituire (default 50, max 500).
        offset: Offset per la paginazione (default 0).
        query: Filtro testuale opzionale — cerca in item_id, item_name,
               title, tags e organization.

    Returns:
        Dict con ``source_id``, ``filters``, ``results`` (lista di item),
        ``returned``, ``has_more``, ``artifact`` e ``cache``.
    """
    if not source_id or not str(source_id).strip():
        return {"error": "invalid_params", "message": "source_id is required"}

    safe_limit = max(1, min(int(limit or 50), 500))
    safe_offset = max(0, int(offset or 0))
    clean_query = (query or "").strip().lower() if query else None

    artifact = _artifact._catalog_inventory_parquet()
    try:
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            with safe_connect() as con:
                columns = set(_artifact._table_columns(con, parquet_path))

                # Colonne da selezionare (sottoinsieme informativo)
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

                if clean_query:
                    search_columns = [
                        col
                        for col in ("item_id", "item_name", "title", "tags", "organization")
                        if col in columns
                    ]
                    if search_columns:
                        like = f"%{clean_query}%"
                        search_clause = (
                            "("
                            + " OR ".join(
                                f"lower(coalesce(cast({col} as varchar), '')) LIKE ?"
                                for col in search_columns
                            )
                            + ")"
                        )
                        where_parts.append(search_clause)
                        params.extend([like] * len(search_columns))

                where = " AND ".join(where_parts)

                # Count totale (per has_more)
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
            "query": clean_query,
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
