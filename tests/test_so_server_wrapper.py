"""Smoke test: verify so_server.py registers 17 MCP tools via create_mcp_server."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Aggiungi mcp/ a sys.path: senza __init__.py non c'è collisione col package PyPI `mcp`.
# so_server.py importa so_server_core come sibling module (stessa directory).
_mcp_dir = Path(__file__).resolve().parents[1] / "mcp"
sys.path.insert(0, str(_mcp_dir))

import so_server  # noqa: E402


def test_mcp_server_registers_17_tools() -> None:
    """Verify all 17 tools are registered on the mcp server object."""
    tools = asyncio.run(so_server.mcp.list_tools())
    tool_names = sorted(t.name for t in tools)

    expected = sorted([
        "so_catalog_inventory_search",
        "so_catalog_signals",
        "so_ckan_package_show",
        "so_discover_sdmx",
        "so_find_by_url",
        "so_html_extract_links",
        "so_infer_topic",
        "so_inventory_diff",
        "so_inventory_query",
        "so_inventory_status",
        "so_probe_url",
        "so_radar_history",
        "so_radar_status_md",
        "so_radar_summary",
        "so_recommend_sources",
        "so_registry_query",
        "so_sparql_query",
    ])

    assert tool_names == expected, f"Expected {expected}, got {tool_names}"


def test_guard_turns_exception_into_error_dict() -> None:
    """guard() from lab_connectors.mcp wraps exceptions as {error, message}."""
    from lab_connectors.mcp import guard

    def raising() -> dict:
        raise ValueError("test error")

    result = guard(raising)
    assert "error" in result
    assert "message" in result
    assert result["error"] == "unexpected_error"
    assert "test error" in result["message"]
