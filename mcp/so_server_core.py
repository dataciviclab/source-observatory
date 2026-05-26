"""
SO MCP core — facade module.

Re-exports all public functions, constants, and helpers from the refactored
``_*.py`` modules for backward compatibility with ``so_server.py`` and tests
that ``import so_server_core as core``.

Each import statement below maps to a specific sub-module.

This file has ``__all__`` and uses ``# noqa: F401`` on its import blocks
so that Ruff treats them as intentional re-exports rather than unused imports.
"""
from __future__ import annotations

__all__ = [
    # Path constants
    "_CHECK_PARQUET",
    "_INVENTORY_PARQUET",
    "_INVENTORY_REPORT",
    "_SIGNALS_JSON",
    "_RADAR_JSON",
    "_RADAR_HISTORY_JSON",
    "_STATUS_MD",
    "_REGISTRY_YAML",
    "_REPO_ROOT",
    "_COLLECTORS_BASE",
    "_DEFAULT_CACHE_MAX_AGE_HOURS",
    "_DEFAULT_GCS_PREFIXES",
    "_SOURCE_CHECK_ARTIFACT",
    "_CATALOG_INVENTORY_ARTIFACT",
    "_CATALOG_INVENTORY_REPORT_ARTIFACT",
    "_FORMAT_BY_CONTENT_TYPE",
    "_FORMAT_BY_SUFFIX",
    # Env loading
    "_load_env_file_once",
    "_env",
    "_artifact_backend",
    "_cache_max_age_hours",
    "_gcs_prefix",
    # Collector base lazy load
    "_get_observatory_get",
    "_collectors_base",
    "observatory_get",
    # Artifact types
    "_ParquetArtifact",
    "_JsonArtifact",
    # Factory functions
    "_source_check_parquet",
    "_catalog_inventory_parquet",
    "_catalog_inventory_report_artifact",
    # Helpers
    "_artifact_not_found",
    "_display_path",
    "_table_columns",
    "_select_expr",
    "_artifact_cache_info",
    "_public_url",
    "_download_public_to_temp",
    "_copy_gcs_to_temp",
    "_resolved_artifact",
    "_resolved_parquet",
    "_resolved_json",
    "_parquet_not_found",
    "_json_not_found",
    "_load_inventory_report",
    "_inventory_source_status",
    # External libs (monkeypatched by tests)
    "requests",
    "HttpClient",
    # Inventory
    "query_inventory",
    "inventory_status",
    "catalog_inventory_search",
    "_source_radar_context",
    "inventory_diff",
    # Signals
    "query_signals",
    # Radar
    "radar_summary",
    "radar_history",
    "radar_status_md",
    "radar_delta",
    # Registry
    "registry_query",
    # Find by URL
    "find_by_url",
    # SDMX
    "discover_sdmx",
    "_read_sdmx_inventory_rows",
    "_score_dataflow",
    # Recommend
    "recommend_sources",
]

# ── Shared artifact infrastructure ──────────────────────────────────────────

# ── External libs (monkeypatched by tests) ──────────────────────────────────
import requests  # noqa: F401
from _artifact import (  # noqa: F401
    _CATALOG_INVENTORY_ARTIFACT,
    _CATALOG_INVENTORY_REPORT_ARTIFACT,
    _CHECK_PARQUET,
    _COLLECTORS_BASE,
    _DEFAULT_CACHE_MAX_AGE_HOURS,
    _DEFAULT_GCS_PREFIXES,
    _FORMAT_BY_CONTENT_TYPE,
    _FORMAT_BY_SUFFIX,
    _INVENTORY_PARQUET,
    _INVENTORY_REPORT,
    _RADAR_HISTORY_JSON,
    _RADAR_JSON,
    _REGISTRY_YAML,
    _REPO_ROOT,
    _SIGNALS_JSON,
    _SOURCE_CHECK_ARTIFACT,
    _STATUS_MD,
    _artifact_backend,
    _artifact_cache_info,
    _artifact_not_found,
    _cache_max_age_hours,
    _catalog_inventory_parquet,
    _catalog_inventory_report_artifact,
    _collectors_base,
    _copy_gcs_to_temp,
    _display_path,
    _download_public_to_temp,
    _env,
    _gcs_prefix,
    _get_observatory_get,
    _inventory_source_status,
    _json_not_found,
    _JsonArtifact,
    _load_env_file_once,
    _load_inventory_report,
    _parquet_not_found,
    _ParquetArtifact,
    _public_url,
    _resolved_artifact,
    _resolved_json,
    _resolved_parquet,
    _select_expr,
    _source_check_parquet,
    _table_columns,
    observatory_get,
)

# ── Find by URL ─────────────────────────────────────────────────────────────
from _find_url import (  # noqa: F401
    find_by_url,
)

# ── Inventory queries ───────────────────────────────────────────────────────
from _inventory import (  # noqa: F401
    _source_radar_context,
    catalog_inventory_search,
    inventory_diff,
    inventory_status,
    query_inventory,
)

# ── Radar queries ───────────────────────────────────────────────────────────
from _radar import (  # noqa: F401
    radar_delta,
    radar_history,
    radar_status_md,
    radar_summary,
)

# ── Source recommendation ───────────────────────────────────────────────────
from _recommend import (  # noqa: F401
    recommend_sources,
)

# ── Registry queries ────────────────────────────────────────────────────────
from _registry import (  # noqa: F401
    registry_query,
)

# ── SDMX discovery ──────────────────────────────────────────────────────────
from _sdmx import (  # noqa: F401
    _read_sdmx_inventory_rows,
    _score_dataflow,
    discover_sdmx,
)

# ── Catalog signals ─────────────────────────────────────────────────────────
from _signals import (  # noqa: F401
    query_signals,
)

from lab_connectors.http import HttpClient  # noqa: F401
