"""
SO MCP Server: read-only layer for Source Observatory artifact inspection.

Run with: python so_mcp/so_server.py

I moduli _*.py in questa directory si importano come sibling
(``import _artifact``, ``from _inventory import ...``) grazie alla directory
stessa aggiunta a ``sys.path`` da ``conftest.py`` (test) o dal runner MCP.
"""
from __future__ import annotations

from typing import Any

from _find_url import find_by_url
from _inventory import (
    catalog_inventory_search,
    inventory_diff,
    inventory_status,
    query_inventory,
)
from _radar import radar_history, radar_status_md, radar_summary
from _recommend import recommend_sources
from _registry import registry_query
from _sdmx import discover_sdmx
from _signals import query_signals
from lab_connectors.mcp import create_mcp_server, guard_timed

mcp = create_mcp_server(
    name="source-observatory",
    instructions=(
        "Read-only MCP per Source Observatory. "
        "Query artifact di source-check, catalog-inventory e catalog-signals "
        "prodotti dalla CI di SO, con probe URL leggero on-demand."
    ),
)


@mcp.tool(
    description="Query source_check_results.parquet: top candidate filtrati per fonte e score.",
    structured_output=True,
)
def so_inventory_query(
    source_id: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
    has_results: bool | None = None,
) -> dict[str, Any]:
    return guard_timed(query_inventory, "so_inventory_query", source_id, min_score, limit, has_results)


@mcp.tool(
    description="Query catalog_signals.json: drift/inventory signals per fonte.",
    structured_output=True,
)
def so_catalog_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    return guard_timed(query_signals, "so_catalog_signals", source_id, limit)


@mcp.tool(
    description="Legge radar_summary.json: health portali e stato GREEN/YELLOW/RED per fonte.",
    structured_output=True,
)
def so_radar_summary(source_id: str | None = None) -> dict[str, Any]:
    return guard_timed(radar_summary, "so_radar_summary", source_id)


@mcp.tool(
    description="Legge radar_history.json: storia probes per fonte, utile per capire streak RED e fonti persistenti.",
    structured_output=True,
)
def so_radar_history(source_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    return guard_timed(radar_history, "so_radar_history", source_id, limit)


@mcp.tool(
    description="Legge STATUS.md: markdown umano con stato radar e sommario per fonte.",
    structured_output=True,
)
def so_radar_status_md() -> dict[str, Any]:
    return guard_timed(radar_status_md, "so_radar_status_md")


@mcp.tool(
    description="Legge catalog_inventory_report.json: stato build inventory per fonte.",
    structured_output=True,
)
def so_inventory_status(source_id: str | None = None) -> dict[str, Any]:
    return guard_timed(inventory_status, "so_inventory_status", source_id)


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
    return guard_timed(catalog_inventory_search, "so_catalog_inventory_search", query, source_id, protocol, limit)


@mcp.tool(
    description="Discovery tematica ISTAT SDMX da artifact locali con relevance score.",
    structured_output=True,
)
def so_discover_sdmx(keywords: list[str], limit: int = 30) -> dict[str, Any]:
    return guard_timed(discover_sdmx, "so_discover_sdmx", keywords, limit)


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
    return guard_timed(registry_query, "so_registry_query", protocol, source_kind, observation_mode, source_id)


@mcp.tool(
    description="Recommend sources from catalog_inventory matching a keyword. "
    "Searches item_name, title, tags, organization, notes_excerpt. "
    "Returns top matching sources with their item counts and organizations.",
    structured_output=True,
)
def so_recommend_sources(keyword: str, limit: int = 10) -> dict[str, Any]:
    return guard_timed(recommend_sources, "so_recommend_sources", keyword, limit)


@mcp.tool(
    description="Compare current inventory against baseline for a source. "
    "Shows item count delta, baseline date, and current count. "
    "Uses catalog_inventory_latest.parquet + catalog_inventory_report.json.",
    structured_output=True,
)
def so_inventory_diff(source_id: str) -> dict[str, Any]:
    return guard_timed(inventory_diff, "so_inventory_diff", source_id)


if __name__ == "__main__":
    mcp.run()
