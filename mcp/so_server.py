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
        inventory_status,
        probe_url,
        query_inventory,
        query_signals,
        radar_delta,
        radar_history,
        radar_status_md,
        radar_summary,
        registry_query,
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
        radar_delta,
        radar_history,
        radar_status_md,
        radar_summary,
        registry_query,
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
    description="Confronta ultimo e penultimo probe del radar: restituisce fonti cambiate, nuove RED, recovery, persistent RED.",
    structured_output=True,
)
def so_radar_delta() -> dict[str, Any]:
    return _guard(radar_delta)


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


if __name__ == "__main__":
    mcp.run()
