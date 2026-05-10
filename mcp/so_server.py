"""
SO MCP Server: read-only layer for Source Observatory artifact inspection.

Run with: python mcp/so_server.py
"""
# ruff: noqa: E402 — import non in cima per via del sys.path collision workaround
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

# ── sys.path collision avoidance ──────────────────────────────────────────────
# La directory locale `mcp/` collide col pacchetto PyPI `mcp`.
# Python ha già cachato `mcp` come pacchetto locale in sys.modules (per via
# di `from mcp.so_server import ...`). Dobbiamo rimuoverlo per permettere
# a `lab_connectors.mcp.core` di importare il VERO pacchetto `mcp`.

# 1. Rimuovi il mcp locale da sys.modules e sys.path
sys.modules.pop("mcp", None)
sys.modules.pop("mcp.server", None)
_MCP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MCP_DIR.parent
sys.path = [p for p in sys.path if Path(p).resolve() not in {_REPO_ROOT}]

# 2. Carica so_server_core via importlib (path assoluto)
_CORE_PATH = _MCP_DIR / "so_server_core.py"
_spec = importlib.util.spec_from_file_location("so_server_core", _CORE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load so_server_core from {_CORE_PATH}")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["so_server_core"] = _mod
_spec.loader.exec_module(_mod)

# Re-exporta tutte le funzioni di so_server_core
catalog_inventory_search = _mod.catalog_inventory_search
discover_sdmx = _mod.discover_sdmx
find_by_url = _mod.find_by_url
infer_topic = _mod.infer_topic
inventory_diff = _mod.inventory_diff
inventory_status = _mod.inventory_status
probe_url = _mod.probe_url
query_inventory = _mod.query_inventory
query_signals = _mod.query_signals
radar_history = _mod.radar_history
radar_status_md = _mod.radar_status_md
radar_summary = _mod.radar_summary
recommend_sources = _mod.recommend_sources
registry_query = _mod.registry_query
_ckan_package_show = _mod._ckan_package_show
_html_extract_links = _mod._html_extract_links
_sparql_query_raw = _mod._sparql_query_raw

# 3. Importa lab_connectors.mcp (mcp non è in sys.modules, sys.path pulito)
from lab_connectors.mcp import create_mcp_server, guard

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
    return guard(query_inventory, source_id, min_score, limit, has_results)


@mcp.tool(
    description="Query catalog_signals.json: drift/inventory signals per fonte.",
    structured_output=True,
)
def so_catalog_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    return guard(query_signals, source_id, limit)


@mcp.tool(
    description="Legge radar_summary.json: health portali e stato GREEN/YELLOW/RED per fonte.",
    structured_output=True,
)
def so_radar_summary(source_id: str | None = None) -> dict[str, Any]:
    return guard(radar_summary, source_id)


@mcp.tool(
    description="Legge radar_history.json: storia probes per fonte, utile per capire streak RED e fonti persistenti.",
    structured_output=True,
)
def so_radar_history(source_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    return guard(radar_history, source_id, limit)


@mcp.tool(
    description="Legge STATUS.md: markdown umano con stato radar e sommario per fonte.",
    structured_output=True,
)
def so_radar_status_md() -> dict[str, Any]:
    return guard(radar_status_md)


@mcp.tool(
    description="Legge catalog_inventory_report.json: stato build inventory per fonte.",
    structured_output=True,
)
def so_inventory_status(source_id: str | None = None) -> dict[str, Any]:
    return guard(inventory_status, source_id)


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
    return guard(catalog_inventory_search, query, source_id, protocol, limit)


@mcp.tool(
    description="Probe leggero di un singolo URL: status, content-type, formato, size, reachability.",
    structured_output=True,
)
def so_probe_url(url: str, timeout: int = 15) -> dict[str, Any]:
    return guard(probe_url, url, timeout)


@mcp.tool(
    description="Discovery tematica ISTAT SDMX da artifact locali con relevance score.",
    structured_output=True,
)
def so_discover_sdmx(keywords: list[str], limit: int = 30) -> dict[str, Any]:
    return guard(discover_sdmx, keywords, limit)


@mcp.tool(
    description="Cerca un URL in source_check_results.parquet e catalog_inventory_latest.parquet per vedere se e' gia' catalogato.",
    structured_output=True,
)
def so_find_by_url(url: str) -> dict[str, Any]:
    return guard(find_by_url, url)


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
    return guard(registry_query, protocol, source_kind, observation_mode, source_id)


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
    return guard(_sparql_query_raw, endpoint, query, timeout, max_rows)


@mcp.tool(
    description="Extract file download links (CSV, JSON, XLSX, ZIP, XML) from an HTML page. "
    "url: page URL. timeout: request timeout in seconds (default 20). "
    "Returns {url, links, total, formats, is_reachable, http_status}.",
    structured_output=True,
)
def so_html_extract_links(url: str, timeout: int = 20) -> dict[str, Any]:
    return guard(_html_extract_links, url, timeout)


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
    return guard(_ckan_package_show, endpoint, package_id, timeout)


@mcp.tool(
    description="Infer thematic topics from any text string (item_name, title, tags, notes, etc.). "
    "Uses a fixed taxonomy of 13 topics: lavoro, economia, sanita, istruzione, trasporti, "
    "ambiente, agricoltura, turismo, giustizia, demografia, energia, commercio. "
    "Returns topics sorted by relevance score (desc), with top_match if dominant (score>=3).",
    structured_output=True,
)
def so_infer_topic(text: str) -> dict[str, Any]:
    return guard(infer_topic, text)


@mcp.tool(
    description="Recommend sources from catalog_inventory matching a keyword. "
    "Searches item_name, title, tags, organization, notes_excerpt. "
    "Returns top matching sources with their item counts and organizations.",
    structured_output=True,
)
def so_recommend_sources(keyword: str, limit: int = 10) -> dict[str, Any]:
    return guard(recommend_sources, keyword, limit)


@mcp.tool(
    description="Compare current inventory against baseline for a source. "
    "Shows item count delta, baseline date, and current count. "
    "Uses catalog_inventory_latest.parquet + catalog_inventory_report.json.",
    structured_output=True,
)
def so_inventory_diff(source_id: str) -> dict[str, Any]:
    return guard(inventory_diff, source_id)


if __name__ == "__main__":
    mcp.run()