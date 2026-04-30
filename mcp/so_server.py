"""
SO MCP Server — readonly layer for Source Observatory artifact inspection.

Run with: fastmcp run source-observatory.mcp.so_server
Requires: pip install mcp fastmcp
"""
from __future__ import annotations

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False

from .so_server_core import query_inventory, query_signals


mcp = FastMCP(
    name="source-observatory",
    instructions=(
        "Read-only MCP per Source Observatory. "
        "Query artifact di source-check, catalog-inventory e catalog-signals "
        "prodotti dalla CI di SO."
    ),
) if _HAS_MCP else None


def _guard(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


if _HAS_MCP:

    @mcp.tool(
        description="Query source_check_results.parquet — inventory results con score e reachable.",
        structured_output=True,
    )
    def so_inventory_query(
        source_id: str | None = None,
        min_score: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Query source_check_results.parquet.

        Args:
            source_id: filter to exact source (e.g. 'inps')
            min_score: filter rows with intake_score >= min_score
            limit: max rows returned (default 50)

        Returns:
            artifact, filters, results list with source_id/item_id/reachable/granularity/intake_score.
        """
        return _guard(query_inventory, source_id, min_score, limit)

    @mcp.tool(
        description="Query catalog_signals.json — drift e inventory signals per source.",
        structured_output=True,
    )
    def so_catalog_signals(
        source_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Query catalog_signals.json.

        Args:
            source_id: filter to exact source (e.g. 'opencoesione')
            limit: return only the last N signals

        Returns:
            artifact, captured_at, signals list with source/protocol/signal_type/result/detail/suggested_action.
        """
        return _guard(query_signals, source_id, limit)


if __name__ == "__main__" and _HAS_MCP:
    mcp.run()
