"""Smoke test: verify so_server.py registers 17 MCP tools via create_mcp_server."""

from __future__ import annotations

import asyncio
import sys
import importlib.util
from pathlib import Path


def _load_so_server() -> "importlib.types.ModuleType":
    """Load so_server.py with the same sys.path isolation it uses at runtime."""
    mcp_dir = Path(__file__).resolve().parents[1] / "mcp"
    repo_root = mcp_dir.parent

    # Same trick so_server.py uses: remove local mcp from sys.modules
    sys.modules.pop("mcp", None)
    sys.modules.pop("mcp.so_server", None)

    # Remove repo root from sys.path so Python picks up the real PyPI mcp package
    _saved_path = list(sys.path)
    sys.path = [p for p in sys.path if Path(p).resolve() not in {repo_root}]

    # Load so_server.py the same way so_server.py loads so_server_core.py
    spec = importlib.util.spec_from_file_location("mcp.so_server", mcp_dir / "so_server.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load so_server from {mcp_dir / 'so_server.py'}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules["mcp.so_server"] = mod
    spec.loader.exec_module(mod)

    sys.path = _saved_path
    return mod


so_server = _load_so_server()


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