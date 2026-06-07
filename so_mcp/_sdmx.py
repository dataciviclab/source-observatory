"""ISTAT SDMX discovery from SO artifact inventory."""

from __future__ import annotations

import re
from typing import Any

from lab_connectors.duckdb import gcs_connect

from . import _artifact


def _score_dataflow(text: str, keywords: list[str]) -> int:
    low = text.lower()
    score = 0
    for keyword in keywords:
        pattern = re.escape(keyword.lower())
        if re.search(rf"\b{pattern}\b", low):
            score += 3
        elif keyword.lower() in low:
            score += 1
    return score


def _read_sdmx_inventory_rows(parquet_path: Any) -> list[dict[str, Any]]:
    with gcs_connect(parquet_path) as con:
        rows = con.execute(
            f"""
            SELECT source_id, item_id, item_name, title, tags, api_base_url, source_url
            FROM "{parquet_path}"
            WHERE source_id = 'istat_sdmx'
            """
        ).fetchall()
    cols = [
        "source_id",
        "item_id",
        "item_name",
        "title",
        "tags",
        "api_base_url",
        "source_url",
    ]
    return [dict(zip(cols, row)) for row in rows]


def discover_sdmx(keywords: list[str] | str, limit: int = 30) -> dict[str, Any]:
    """Discover ISTAT SDMX dataflows from local SO artifacts."""
    if isinstance(keywords, str):
        clean_keywords = [part.strip().lower() for part in keywords.split(",") if part.strip()]
    else:
        clean_keywords = [str(part).strip().lower() for part in keywords if str(part).strip()]
    if not clean_keywords:
        return {"error": "empty_keywords", "message": "Provide at least one keyword."}

    safe_limit = max(1, min(int(limit or 30), 100))
    try:
        artifact = _artifact._catalog_inventory_parquet()
        with _artifact._resolved_parquet(artifact) as (resolved_path, cache):
            rows = _read_sdmx_inventory_rows(resolved_path)
    except FileNotFoundError:
        return _artifact._parquet_not_found(_artifact._catalog_inventory_parquet())

    if not rows:
        source_status = _artifact._inventory_source_status("istat_sdmx")
        return {
            "error": "source_unavailable",
            "artifact": _artifact._display_path(_artifact._INVENTORY_PARQUET),
            "cache": cache,
            "source_id": "istat_sdmx",
            "message": "No ISTAT SDMX rows found in catalog_inventory_latest.parquet.",
            "source_status": source_status,
            "filters": {"keywords": clean_keywords, "limit": safe_limit},
            "dataflows": [],
            "returned": 0,
            "matched": 0,
        }

    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        text = " ".join(
            str(item.get(key) or "") for key in ("item_id", "item_name", "title", "tags")
        )
        score = _score_dataflow(text, clean_keywords)
        if score <= 0:
            continue
        item["relevance_score"] = score
        results.append(item)

    results.sort(
        key=lambda item: (
            item["relevance_score"],
            str(item.get("title") or item.get("item_name") or ""),
        ),
        reverse=True,
    )
    return {
        "artifact": _artifact._display_path(_artifact._INVENTORY_PARQUET),
        "cache": cache,
        "filters": {"keywords": clean_keywords, "limit": safe_limit},
        "dataflows": results[:safe_limit],
        "returned": min(len(results), safe_limit),
        "matched": len(results),
    }
