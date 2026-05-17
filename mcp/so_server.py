"""
SO MCP Server: read-only layer for Source Observatory artifact inspection.

Run with: python mcp/so_server.py

Nota: mcp/ non ha __init__.py (rimosso deliberatamente) per evitare collisione
col pacchetto PyPI `mcp`. so_server_core.py e so_server.py sono importabili
come moduli sibling senza creare un package `mcp` locale.
"""
from __future__ import annotations

from typing import Any

import so_server_core
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
    return guard_timed(so_server_core.query_inventory, "so_inventory_query", source_id, min_score, limit, has_results, logger_name="source-observatory")


@mcp.tool(
    description="Query catalog_signals.json: drift/inventory signals per fonte.",
    structured_output=True,
)
def so_catalog_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    return guard_timed(so_server_core.query_signals, "so_catalog_signals", source_id, limit, logger_name="source-observatory")


@mcp.tool(
    description="Legge radar_summary.json: health portali e stato GREEN/YELLOW/RED per fonte.",
    structured_output=True,
)
def so_radar_summary(source_id: str | None = None) -> dict[str, Any]:
    return guard_timed(so_server_core.radar_summary, "so_radar_summary", source_id, logger_name="source-observatory")


@mcp.tool(
    description="Legge radar_history.json: storia probes per fonte, utile per capire streak RED e fonti persistenti.",
    structured_output=True,
)
def so_radar_history(source_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    return guard_timed(so_server_core.radar_history, "so_radar_history", source_id, limit, logger_name="source-observatory")


@mcp.tool(
    description="Legge STATUS.md: markdown umano con stato radar e sommario per fonte.",
    structured_output=True,
)
def so_radar_status_md() -> dict[str, Any]:
    return guard_timed(so_server_core.radar_status_md, "so_radar_status_md", logger_name="source-observatory")


@mcp.tool(
    description="Legge catalog_inventory_report.json: stato build inventory per fonte.",
    structured_output=True,
)
def so_inventory_status(source_id: str | None = None) -> dict[str, Any]:
    return guard_timed(so_server_core.inventory_status, "so_inventory_status", source_id, logger_name="source-observatory")


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
    return guard_timed(so_server_core.catalog_inventory_search, "so_catalog_inventory_search", query, source_id, protocol, limit, logger_name="source-observatory")


@mcp.tool(
    description="Probe leggero di un singolo URL: status, content-type, formato, size, reachability.",
    structured_output=True,
)
def so_probe_url(url: str, timeout: int = 15) -> dict[str, Any]:
    return guard_timed(so_server_core.probe_url, "so_probe_url", url, timeout, logger_name="source-observatory")


@mcp.tool(
    description="Discovery tematica ISTAT SDMX da artifact locali con relevance score.",
    structured_output=True,
)
def so_discover_sdmx(keywords: list[str], limit: int = 30) -> dict[str, Any]:
    return guard_timed(so_server_core.discover_sdmx, "so_discover_sdmx", keywords, limit, logger_name="source-observatory")


@mcp.tool(
    description="Cerca un URL o testo in source_check_results (colonne URL) e catalog_inventory_latest (URL + item_name, item_id, title, notes_excerpt). "
    "Usa LIKE %query% — utile per trovare item per URL, filename, ID o nome.",
    structured_output=True,
)
def so_find_by_url(url: str) -> dict[str, Any]:
    return guard_timed(so_server_core.find_by_url, "so_find_by_url", url, logger_name="source-observatory")


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
    return guard_timed(so_server_core.registry_query, "so_registry_query", protocol, source_kind, observation_mode, source_id, logger_name="source-observatory")


@mcp.tool(
    description="Execute a SPARQL SELECT query against a public endpoint and return tabular results. "
    "endpoint: SPARQL URL (http/https). query: SPARQL query string. "
    "timeout: seconds (1-120, default 60). max_rows: maximum rows (1-500, default 500).",
    structured_output=True,
)
def so_sparql_query(
    endpoint: str,
    query: str,
    timeout: int = 60,
    max_rows: int = 500,
) -> dict[str, Any]:
    return guard_timed(so_server_core._sparql_query_raw, "so_sparql_query", endpoint, query, timeout, max_rows, logger_name="source-observatory")


@mcp.tool(
    description="Extract file download links (CSV, JSON, XLSX, ZIP, XML) from an HTML page. "
    "url: page URL. timeout: request timeout in seconds (default 20). "
    "Returns {url, links, total, formats, is_reachable, http_status}.",
    structured_output=True,
)
def so_html_extract_links(url: str, timeout: int = 20) -> dict[str, Any]:
    return guard_timed(so_server_core._html_extract_links, "so_html_extract_links", url, timeout, logger_name="source-observatory")


@mcp.tool(
    description="Fetch a single CKAN dataset (package_show) and return enriched metadata. "
    "endpoint: CKAN portal base URL (e.g. https://dati.gov.it). "
    "package_id: dataset ID or name. "
    "Returns item_id, name, title, notes_excerpt, organization, tags, format, "
    "resource_count, datastore_active, landing_page, distribution_url, source_url. "
    "On error returns {error, message}.",
    structured_output=True,
)
def so_ckan_package_show(endpoint: str, package_id: str, timeout: int = 30) -> dict[str, Any]:
    return guard_timed(so_server_core._ckan_package_show, "so_ckan_package_show", endpoint, package_id, timeout, logger_name="source-observatory")


@mcp.tool(
    description="Infer thematic topics from any text string (item_name, title, tags, notes, etc.). "
    "Uses a fixed taxonomy of 20 topics: lavoro, economia, sanita, istruzione, trasporti, "
    "ambiente, agricoltura, turismo, giustizia, demografia, energia, commercio, "
    "welfare, previdenza, casa, cultura, bilancio, innovazione, sicurezza. "
    "Returns topics sorted by relevance score (desc), with top_match if dominant (score>=3).",
    structured_output=True,
)
def so_infer_topic(text: str) -> dict[str, Any]:
    return guard_timed(so_server_core.infer_topic, "so_infer_topic", text, logger_name="source-observatory")


@mcp.tool(
    description="Recommend sources from catalog_inventory matching a keyword. "
    "Searches item_name, title, tags, organization, notes_excerpt. "
    "Returns top matching sources with their item counts and organizations.",
    structured_output=True,
)
def so_recommend_sources(keyword: str, limit: int = 10) -> dict[str, Any]:
    return guard_timed(so_server_core.recommend_sources, "so_recommend_sources", keyword, limit, logger_name="source-observatory")


@mcp.tool(
    description="Compare current inventory against baseline for a source. "
    "Shows item count delta, baseline date, and current count. "
    "Uses catalog_inventory_latest.parquet + catalog_inventory_report.json.",
    structured_output=True,
)
def so_inventory_diff(source_id: str) -> dict[str, Any]:
    return guard_timed(so_server_core.inventory_diff, "so_inventory_diff", source_id, logger_name="source-observatory")


if __name__ == "__main__":
    mcp.run()
