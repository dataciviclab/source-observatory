"""Find-by-URL: search across validated.parquet and catalog_inventory."""

from __future__ import annotations

from typing import Any

from lab_connectors.duckdb import gcs_connect

from . import _artifact


def find_by_url(url: str) -> dict[str, Any]:
    """Find a URL across validated.parquet and catalog_inventory."""
    clean_url = (url or "").strip()
    if not clean_url:
        return {"error": "empty_url", "message": "Provide a non-empty URL."}

    results: dict[str, Any] = {
        "query_url": clean_url,
        "validated_groups": [],
        "catalog_inventory": [],
    }

    validated_artifact = _artifact._source_check_parquet()
    try:
        with _artifact._resolved_parquet(validated_artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            with gcs_connect(resolved_path) as con:
                cols = _artifact._table_columns(con, parquet_path)
                url_cols = [
                    c
                    for c in cols
                    if c in ("url", "distribution_url", "landing_page", "source_url")
                ]
                if not url_cols:
                    results["validated_error"] = "No URL columns found in parquet"
                else:
                    where = " OR ".join(
                        f"lower(coalesce(cast({c} as varchar), '')) LIKE ?" for c in url_cols
                    )
                    like = f"%{clean_url.lower()}%"
                    sql = f'SELECT * FROM "{parquet_path}" WHERE {where} LIMIT 10'
                    rows = con.execute(sql, [like] * len(url_cols)).fetchall()
                    results["validated_groups"] = [dict(zip(cols, row)) for row in rows]
                    results["validated_cache"] = cache
    except FileNotFoundError:
        results["validated_error"] = f"{validated_artifact.name} not found"

    catalog_artifact = _artifact._catalog_inventory_parquet()
    try:
        with _artifact._resolved_parquet(catalog_artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            with gcs_connect(resolved_path) as con:
                cols = _artifact._table_columns(con, parquet_path)
                search_cols = [
                    c
                    for c in cols
                    if c
                    in (
                        "url",
                        "url_checked",
                        "distribution_url",
                        "landing_page",
                        "source_url",
                        "item_name",
                        "item_id",
                        "title",
                        "notes_excerpt",
                    )
                ]
                if not search_cols:
                    results["catalog_inventory_error"] = "No searchable columns found in parquet"
                else:
                    where = " OR ".join(
                        f"lower(coalesce(cast({c} as varchar), '')) LIKE ?" for c in search_cols
                    )
                    like = f"%{clean_url.lower()}%"
                    sql = f'SELECT * FROM "{parquet_path}" WHERE {where} LIMIT 10'
                    rows = con.execute(sql, [like] * len(search_cols)).fetchall()
                    results["catalog_inventory"] = [dict(zip(cols, row)) for row in rows]
                    results["catalog_inventory_cache"] = cache
    except FileNotFoundError:
        results["catalog_inventory_error"] = f"{catalog_artifact.name} not found"

    return results
