"""Source recommendation from catalog inventory."""

from __future__ import annotations

from typing import Any

import _artifact
from lab_connectors.duckdb import safe_connect


def recommend_sources(keyword: str, limit: int = 10) -> dict[str, Any]:
    """Recommend sources from inventory matching a keyword.

    Searches across item_name, title, tags, organization, notes_excerpt.
    Returns top matching sources with their item counts.
    """
    if not keyword or not str(keyword).strip():
        return {"error": "empty_keyword", "message": "Provide non-empty keyword."}

    safe_limit = max(1, min(int(limit or 10), 50))
    keyword_low = str(keyword).strip().lower()

    try:
        artifact = _artifact._catalog_inventory_parquet()
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            with safe_connect() as con:
                total_row = con.execute(
                    f'SELECT COUNT(*) FROM "{resolved_path}"'
                ).fetchone()
                total_items = total_row[0] if total_row else 0

                rows = con.execute(
                    f'''
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
                    ''',
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
