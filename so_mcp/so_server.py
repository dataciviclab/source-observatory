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
from ._radar import radar_history, radar_summary
from ._registry import registry_query
from ._signals import query_signals
from ._source_check import inventory_diff, inventory_status, query_inventory

mcp = create_mcp_server(
    name="source-observatory",
    instructions=(
        "Read-only MCP per Source Observatory. "
        "Query artifact di source-check, catalog-inventory e catalog-signals "
        "prodotti dalla CI di SO, con probe URL leggero on-demand."
    ),
)

# Cache TTL 120s per risposte ripetute (stesso pattern di clean-query PR #607)
_query_cache = TtlCache(ttl_seconds=120)


# ─── Tool 1/7: Registry ───────────────────────────────────────────────────────


@mcp.tool(
    description="Interroga sources_registry.yaml: filtra per protocol, source_kind, observation_mode o cerca per source_id.",
    structured_output=True,
)
def so_registry_query(
    protocol: str | None = None,
    source_kind: str | None = None,
    observation_mode: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    return guard_timed(
        registry_query, "so_registry_query", protocol, source_kind, observation_mode, source_id
    )


# ─── Tool 2/7: Radar ──────────────────────────────────────────────────────────


@mcp.tool(
    description="Legge radar_summary.json: health portali e stato GREEN/YELLOW/RED per fonte. "
    "Con include_history=True include anche la cronologia probe recente.",
    structured_output=True,
)
def so_radar_summary(
    source_id: str | None = None,
    include_history: bool = False,
) -> dict[str, Any]:
    cache_key = ("radar_summary", source_id, include_history)
    cached = _query_cache.get(cache_key)
    if cached is not None:
        return cached

    def _exec() -> dict[str, Any]:
        result = radar_summary(source_id)
        if include_history:
            result["history"] = radar_history(source_id, limit=5)
        return result

    result = guard_timed(_exec, "so_radar_summary")
    _query_cache.set(cache_key, result)
    return result


# ─── Tool 3/7: Inventory Search ───────────────────────────────────────────────


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


# ─── Tool 4/7: Source Check ────────────────────────────────────────────────────


@mcp.tool(
    description="Interroga i risultati source-check. "
    "Modalità: query= su source_check_results.parquet (con filtri source_id, min_score, ecc.), "
    "oppure con include_diff=True per leggere inventario e delta item per fonte.",
    structured_output=True,
)
def so_source_check(
    source_id: str | None = None,
    min_score: int | None = None,
    min_paqa_score: int | None = None,
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

    # query mode
    query_cache_key = (
        "source_check_query",
        source_id,
        min_score,
        min_paqa_score,
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
        min_paqa_score,
        limit,
        has_results,
        grouped,
    )
    _query_cache.set(query_cache_key, result)
    return result


# ─── Tool 5/7: Signals ────────────────────────────────────────────────────────


@mcp.tool(
    description="Query catalog_signals.json: drift/inventory signals per fonte.",
    structured_output=True,
)
def so_catalog_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    cache_key = ("catalog_signals", source_id, limit)
    cached = _query_cache.get(cache_key)
    if cached is not None:
        return cached

    result = guard_timed(query_signals, "so_catalog_signals", source_id, limit)
    _query_cache.set(cache_key, result)
    return result


# ─── Tool 6/7: Find by URL ────────────────────────────────────────────────────


@mcp.tool(
    description="Cerca un URL o testo in source_check_results (colonne URL) e catalog_inventory_latest "
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


# ─── Tool 7/7: Source Overview (composito) ────────────────────────────────────


@mcp.tool(
    description=(
        "Overview completo di una fonte: registry, radar, inventory, "
        "delta item count, signals recenti. Compone registry_query + "
        "radar_summary + inventory_status + inventory_diff + "
        "catalog_signals in una singola chiamata."
    ),
    structured_output=True,
)
def so_source_overview(source_id: str) -> dict[str, Any]:
    """Overview completo di una fonte in un giro solo."""

    def _exec() -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_id": source_id,
            "registry": registry_query(source_id=source_id),
            "radar": radar_summary(source_id),
            "inventory_status": inventory_status(source_id),
            "inventory_diff": inventory_diff(source_id),
            "signals": query_signals(source_id, limit=5),
        }
        return result

    return guard_timed(_exec, "so_source_overview")


def main() -> None:
    """Entry point per l'MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
