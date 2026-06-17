"""
SO MCP Server: read-only layer for Source Observatory artifact inspection.

Run with: python so_mcp/so_server.py

I moduli _*.py in questa directory si importano come sibling
(``import _artifact``, ``from _inventory import ...``) grazie alla directory
stessa aggiunta a ``sys.path`` da ``conftest.py`` (test) o dal runner MCP.
"""

from __future__ import annotations

from typing import Any

from lab_connectors.mcp import create_mcp_server, guard_timed

from ._discovery import list_source_items
from ._find_url import find_by_url
from ._inventory import (
    catalog_inventory_search,
    inventory_diff,
    inventory_status,
    query_inventory,
)
from ._radar import radar_history, radar_summary
from ._recommend import recommend_sources
from ._registry import registry_query
from ._signals import query_signals

mcp = create_mcp_server(
    name="source-observatory",
    instructions=(
        "Read-only MCP per Source Observatory. "
        "Query artifact di source-check, catalog-inventory e catalog-signals "
        "prodotti dalla CI di SO, con probe URL leggero on-demand."
    ),
)


@mcp.tool(
    description="Query source_check_results.parquet: top candidate filtrati per fonte, intake_score e paqa_score. "
    "Con grouped=True, aggrega per dataset_group (stesso dataset multi-anno/versione).",
    structured_output=True,
)
def so_inventory_query(
    source_id: str | None = None,
    min_score: int | None = None,
    min_paqa_score: int | None = None,
    limit: int = 50,
    has_results: bool | None = None,
    grouped: bool = False,
) -> dict[str, Any]:
    return guard_timed(
        query_inventory,
        "so_inventory_query",
        source_id,
        min_score,
        min_paqa_score,
        limit,
        has_results,
        grouped,
    )


@mcp.tool(
    description="Query catalog_signals.json: drift/inventory signals per fonte.",
    structured_output=True,
)
def so_catalog_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    return guard_timed(query_signals, "so_catalog_signals", source_id, limit)


@mcp.tool(
    description="Legge radar_summary.json: health portali e stato GREEN/YELLOW/RED per fonte. "
    "Con include_history=True include anche la cronologia probe recente.",
    structured_output=True,
)
def so_radar_summary(
    source_id: str | None = None,
    include_history: bool = False,
) -> dict[str, Any]:
    def _exec() -> dict[str, Any]:
        result = radar_summary(source_id)
        if include_history:
            result["history"] = radar_history(source_id, limit=5)
        return result

    return guard_timed(_exec, "so_radar_summary")


@mcp.tool(
    description="Legge catalog_inventory_report.json: stato build inventory per fonte. "
    "Con include_diff=True include anche il delta item count rispetto al baseline "
    "(richiede source_id esplicito).",
    structured_output=True,
)
def so_inventory_status(
    source_id: str | None = None,
    include_diff: bool = False,
) -> dict[str, Any]:
    def _exec() -> dict[str, Any]:
        if include_diff and not source_id:
            return {
                "error": "invalid_params",
                "message": "include_diff=True richiede source_id esplicito.",
            }
        result = inventory_status(source_id)
        if include_diff and source_id:
            result["diff"] = inventory_diff(source_id)
        return result

    return guard_timed(_exec, "so_inventory_status")


@mcp.tool(
    description="Cerca item in catalog_inventory_latest.parquet per testo, fonte e protocollo.",
    structured_output=True,
)
def so_catalog_inventory_search(
    query: str,
    source_id: str | None = None,
    protocol: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    return guard_timed(
        catalog_inventory_search, "so_catalog_inventory_search", query, source_id, protocol, limit
    )


@mcp.tool(
    description="Cerca un URL o testo in source_check_results (colonne URL) e catalog_inventory_latest (URL + item_name, item_id, title, notes_excerpt). "
    "Usa LIKE %query% — utile per trovare item per URL, filename, ID o nome.",
    structured_output=True,
)
def so_find_by_url(url: str) -> dict[str, Any]:
    return guard_timed(find_by_url, "so_find_by_url", url)


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


@mcp.tool(
    description="Recommend sources from catalog_inventory matching a keyword. "
    "Searches item_name, title, tags, organization, notes_excerpt. "
    "Returns top matching sources with their item counts and organizations.",
    structured_output=True,
)
def so_recommend_sources(keyword: str, limit: int = 10) -> dict[str, Any]:
    return guard_timed(recommend_sources, "so_recommend_sources", keyword, limit)


@mcp.tool(
    description="Elenca gli item (dataset, dataflow, risorsa) di una fonte "
    "dal catalog_inventory_latest.parquet. "
    "Accetta source_id (richiesto), limit, offset e query testuale opzionale "
    "su item_id, item_name, title, tags e organization.",
    structured_output=True,
)
def so_list_source_items(
    source_id: str,
    limit: int = 50,
    offset: int = 0,
    query: str | None = None,
) -> dict[str, Any]:
    return guard_timed(list_source_items, "so_list_source_items", source_id, limit, offset, query)


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
