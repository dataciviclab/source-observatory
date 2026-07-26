"""
SO MCP Server: read-only layer for Source Observatory artifact inspection.

Run with: python so_mcp/so_server.py

I moduli _*.py in questa directory si importano come sibling
(``import _artifact``, ``from _inventory_search import ...``) grazie alla directory
stessa aggiunta a ``sys.path`` da ``conftest.py`` (test) o dal runner MCP.
"""

from __future__ import annotations

from typing import Any

from lab_connectors.mcp import (
    TtlCache,
    create_mcp_server,
    guard_timed,
)

from ._find_url import find_by_url
from ._inventory_search import inventory_search
from ._report import dashboard, source_report
from ._source_check import inventory_diff, inventory_status, query_inventory

mcp = create_mcp_server(
    name="source-observatory",
    instructions=(
        "Read-only MCP per Source Observatory. "
        "Report per fonte (so_source_report), dashboard KPI (so_dashboard), "
        "ricerca inventory (so_inventory_search, so_source_check) "
        "su validated.parquet (reachable + schema) e URL (so_find_by_url)."
    ),
)

# Cache TTL 120s per risposte ripetute (stesso pattern di clean-query PR #607)
_query_cache: TtlCache[tuple[Any, ...], dict[str, Any]] = TtlCache(ttl_seconds=120)


# ─── Tool 1/5: Inventory Search ─────────────────────────────────────────────


@mcp.tool(
    description="Cerca nel catalogo inventory (catalog_inventory_latest.parquet). "
    "Modalità automatica: passa keyword= per raggruppare per fonte (recommend), "
    "source_id= senza query per listare item con paginazione, "
    "query= per full-text search (con source_id= e/o protocol= opzionali).",
    structured_output=True,
)
def so_inventory_search(
    query: str | None = None,
    source_id: str | None = None,
    protocol: str | None = None,
    keyword: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    cache_key = ("inventory_search", query, source_id, protocol, keyword, limit, offset)
    cached = _query_cache.get(cache_key)
    if cached is not None:
        return cached

    result = guard_timed(
        inventory_search, "so_inventory_search", query, source_id, protocol, keyword, limit, offset
    )
    _query_cache.set(cache_key, result)
    return result


# ─── Tool 2/5: Source Check ──────────────────────────────────────────────────


@mcp.tool(
    description="Interroga i risultati della pipeline (validated.parquet). "
    "Filtri: source_id, min_score (readiness_score 0-4), has_results (reachable). "
    "Con grouped=True raggruppa per dataset logico. "
    "Con include_diff=True mostra inventario e delta item per fonte.",
    structured_output=True,
)
def so_source_check(
    source_id: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
    has_results: bool | None = None,
    grouped: bool = False,
    include_diff: bool = False,
) -> dict[str, Any]:
    # Se include_diff=True → modalità status/diff
    if include_diff:
        cache_key = ("source_check_diff", source_id)
        cached = _query_cache.get(cache_key)
        if cached is not None:
            return cached

        def _exec_diff() -> dict[str, Any]:
            status = inventory_status(source_id)
            if source_id:
                status["diff"] = inventory_diff(source_id)
            return status

        result = guard_timed(_exec_diff, "so_source_check")
        _query_cache.set(cache_key, result)
        return result

    # query mode — min_paqa_score rimosso (non più calcolato)
    query_cache_key = (
        "source_check_query",
        source_id,
        min_score,
        limit,
        has_results,
        grouped,
    )
    cached = _query_cache.get(query_cache_key)
    if cached is not None:
        return cached

    result = guard_timed(
        query_inventory,
        "so_source_check",
        source_id,
        min_score,
        None,  # min_paqa_score — kept as None for backward compat
        limit,
        has_results,
        grouped,
    )
    _query_cache.set(query_cache_key, result)
    return result


# ─── Tool 3/5: Find by URL ──────────────────────────────────────────────────


@mcp.tool(
    description="Cerca un URL o testo in validated.parquet (colonne URL) e catalog_inventory_latest "
    "(URL + item_name, item_id, title, notes_excerpt). "
    "Usa LIKE %%query%% — utile per trovare item per URL, filename, ID o nome.",
    structured_output=True,
)
def so_find_by_url(url: str) -> dict[str, Any]:
    cache_key = ("find_by_url", url)
    cached = _query_cache.get(cache_key)
    if cached is not None:
        return cached

    result = guard_timed(find_by_url, "so_find_by_url", url)
    _query_cache.set(cache_key, result)
    return result


# ─── Tool 4/5: Source Report (da JSON — consumo standard) ───────────────────


@mcp.tool(
    description=(
        "📋 Report sintetico di una fonte: health, inventory, source-check, "
        "datasets_in_use, segnali e verdict operativo. "
        "Legge da data/reports/source_reports/{source_id}.json (git, prodotto dalla CI). "
        "Sostituisce so_source_overview per il consumo standard."
    ),
    structured_output=True,
)
def so_source_report(source_id: str) -> dict[str, Any]:
    return guard_timed(source_report, "so_source_report", source_id)


# ─── Tool 5/5: Dashboard (da JSON — consumo standard) ───────────────────────


@mcp.tool(
    description=(
        "📊 Dashboard di tutte le fonti: KPI riassuntivi per ogni fonte "
        "(protocol, radar, inventory_items, scored_items, intake_candidates, "
        "datasets_in_use, verdict). "
        "Legge da data/reports/sources_dashboard.json (git, prodotto dalla CI)."
    ),
    structured_output=True,
)
def so_dashboard() -> dict[str, Any]:
    return guard_timed(dashboard, "so_dashboard")


def main() -> None:
    """Entry point per l'MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
