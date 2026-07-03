"""Smoke test: verify so_server.py registers 7 MCP tools via create_mcp_server."""

from __future__ import annotations

import asyncio

import pytest

from so_mcp import so_server


def test_mcp_server_registers_7_tools() -> None:
    """Verify all 7 tools are registered on the mcp server object."""
    tools = asyncio.run(so_server.mcp.list_tools())
    tool_names = sorted(t.name for t in tools)

    expected = sorted(
        [
            "so_catalog_signals",
            "so_find_by_url",
            "so_inventory_search",
            "so_radar_summary",
            "so_registry_query",
            "so_source_check",
            "so_source_overview",
        ]
    )

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


def test_guard_timed_logs_and_wraps_exception() -> None:
    """guard_timed() wraps exceptions and includes timing metadata in logs."""
    from lab_connectors.mcp import guard_timed

    def raising() -> dict:
        raise ValueError("test timed error")

    result = guard_timed(raising, "test_tool", logger_name="test-server")
    assert "error" in result
    assert "message" in result
    assert result["error"] == "unexpected_error"
    assert "test timed error" in result["message"]


def test_guard_timed_returns_dict_result() -> None:
    """guard_timed() passes through a successful dict result unchanged."""
    from lab_connectors.mcp import guard_timed

    def working() -> dict:
        return {"result_key": 42, "nested": {"a": 1}}

    result = guard_timed(working, "working_tool", logger_name="test-server")
    assert result == {"result_key": 42, "nested": {"a": 1}}


pytestmark = pytest.mark.smoke
