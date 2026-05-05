"""
SO MCP Server: read-only layer for Source Observatory artifact inspection.

Run with: python /path/to/source-observatory/mcp/so_server.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_MCP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MCP_DIR.parent
_ORIGINAL_SYS_PATH = list(sys.path)
sys.path = [
    path
    for path in sys.path
    if Path(path or ".").resolve() not in {_MCP_DIR, _REPO_ROOT}
]
try:
    from mcp.server.fastmcp import FastMCP
finally:
    sys.path = _ORIGINAL_SYS_PATH

try:
    from .so_server_core import (
        catalog_inventory_search,
        discover_sdmx,
        find_by_url,
        infer_topic,
        inventory_diff,
        inventory_status,
        probe_url,
        query_inventory,
        query_signals,
        radar_history,
        radar_status_md,
        radar_summary,
        recommend_sources,
        registry_query,
        _ckan_package_show,
    )
except ImportError:
    if str(_MCP_DIR) not in sys.path:
        sys.path.insert(0, str(_MCP_DIR))
    from so_server_core import (  # type: ignore[no-redef]
        catalog_inventory_search,
        discover_sdmx,
        find_by_url,
        inventory_status,
        probe_url,
        query_inventory,
        query_signals,
        radar_history,
        radar_status_md,
        radar_summary,
        registry_query,
        _ckan_package_show,
        _html_extract_links,
        _sparql_query_raw,
    )


mcp = FastMCP(
    name="source-observatory",
    instructions=(
        "Read-only MCP per Source Observatory. "
        "Query artifact di source-check, catalog-inventory e catalog-signals "
        "prodotti dalla CI di SO, con probe URL leggero on-demand."
    ),
)


def _guard(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


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
    return _guard(query_inventory, source_id, min_score, limit, has_results)


@mcp.tool(
    description="Query catalog_signals.json: drift/inventory signals per fonte.",
    structured_output=True,
)
def so_catalog_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    return _guard(query_signals, source_id, limit)


@mcp.tool(
    description="Legge radar_summary.json: health portali e stato GREEN/YELLOW/RED per fonte.",
    structured_output=True,
)
def so_radar_summary(source_id: str | None = None) -> dict[str, Any]:
    return _guard(radar_summary, source_id)


@mcp.tool(
    description="Legge radar_history.json: storia probes per fonte, utile per capire streak RED e fonti persistenti.",
    structured_output=True,
)
def so_radar_history(source_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    return _guard(radar_history, source_id, limit)


@mcp.tool(
    description="Legge STATUS.md: markdown umano con stato radar e sommario per fonte.",
    structured_output=True,
)
def so_radar_status_md() -> dict[str, Any]:
    return _guard(radar_status_md)


@mcp.tool(
    description="Legge catalog_inventory_report.json: stato build inventory per fonte.",
    structured_output=True,
)
def so_inventory_status(source_id: str | None = None) -> dict[str, Any]:
    return _guard(inventory_status, source_id)


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
    return _guard(catalog_inventory_search, query, source_id, protocol, limit)


@mcp.tool(
    description="Probe leggero di un singolo URL: status, content-type, formato, size, reachability.",
    structured_output=True,
)
def so_probe_url(url: str, timeout: int = 15) -> dict[str, Any]:
    return _guard(probe_url, url, timeout)


@mcp.tool(
    description="Discovery tematica ISTAT SDMX da artifact locali con relevance score.",
    structured_output=True,
)
def so_discover_sdmx(keywords: list[str], limit: int = 30) -> dict[str, Any]:
    return _guard(discover_sdmx, keywords, limit)


@mcp.tool(
    description="Cerca un URL in source_check_results.parquet e catalog_inventory_latest.parquet per vedere se e' gia' catalogato.",
    structured_output=True,
)
def so_find_by_url(url: str) -> dict[str, Any]:
    return _guard(find_by_url, url)


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
    return _guard(registry_query, protocol, source_kind, observation_mode, source_id)


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
    return _guard(_sparql_query_raw, endpoint, query, timeout, max_rows)


@mcp.tool(
    description="Extract file download links (CSV, JSON, XLSX, ZIP, XML) from an HTML page. "
    "url: page URL. timeout: request timeout in seconds (default 20). "
    "Returns {url, links, total, formats, is_reachable, http_status}.",
    structured_output=True,
)
def so_html_extract_links(url: str, timeout: int = 20) -> dict[str, Any]:
    return _guard(_html_extract_links, url, timeout)


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
    return _guard(_ckan_package_show, endpoint, package_id, timeout)


@mcp.tool(
    description="Infer thematic topics from any text string (item_name, title, tags, notes, etc.). "
    "Uses a fixed taxonomy of 13 topics: lavoro, economia, sanita, istruzione, trasporti, "
    "ambiente, agricoltura, turismo, giustizia, demografia, energia, commercio. "
    "Returns topics sorted by relevance score (desc), with top_match if dominant (score>=3).",
    structured_output=True,
)
def so_infer_topic(text: str) -> dict[str, Any]:
    return _guard(infer_topic, text)


@mcp.tool(
    description="Recommend sources from catalog_inventory matching a keyword. "
    "Searches item_name, title, tags, organization, notes_excerpt. "
    "Returns top matching sources with item counts and organizations.",
    structured_output=True,
)
def so_recommend_sources(keyword: str, limit: int = 10) -> dict[str, Any]:
    return _guard(recommend_sources, keyword, limit)


@mcp.tool(
    description="Compare current inventory against baseline for a source. "
    "Shows item count delta, baseline date, and current count. "
    "Uses catalog_inventory_latest.parquet + catalog_inventory_report.json. "
    "days: window for baseline comparison (default 7, max 90).",
    structured_output=True,
)
def so_inventory_diff(source_id: str, days: int = 7) -> dict[str, Any]:
    return _guard(inventory_diff, source_id, days)


if __name__ == "__main__":
    mcp.run()
