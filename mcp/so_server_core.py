"""
SO MCP core — facade module.

Re-exports all public functions, constants, and helpers from the refactored
``_*.py`` modules for backward compatibility with ``so_server.py`` and tests
that ``import so_server_core as core``.

Each import statement below maps to a specific sub-module.
"""

# ── Shared artifact infrastructure ──────────────────────────────────────────

from _artifact import (
    # Path constants (monkeypatched by tests)
    _CHECK_PARQUET,
    _INVENTORY_PARQUET,
    _INVENTORY_REPORT,
    _SIGNALS_JSON,
    _RADAR_JSON,
    _RADAR_HISTORY_JSON,
    _STATUS_MD,
    _REGISTRY_YAML,
    _REPO_ROOT,
    _COLLECTORS_BASE,
    _DEFAULT_CACHE_MAX_AGE_HOURS,
    _DEFAULT_GCS_PREFIXES,
    _SOURCE_CHECK_ARTIFACT,
    _CATALOG_INVENTORY_ARTIFACT,
    _CATALOG_INVENTORY_REPORT_ARTIFACT,
    _FORMAT_BY_CONTENT_TYPE,
    _FORMAT_BY_SUFFIX,
    # Env loading
    _load_env_file_once,
    _env,
    _artifact_backend,
    _cache_max_age_hours,
    _gcs_prefix,
    # Collector base lazy load
    _get_observatory_get,
    _collectors_base,
    observatory_get,
    # Artifact types
    _ParquetArtifact,
    _JsonArtifact,
    # Factory functions
    _source_check_parquet,
    _catalog_inventory_parquet,
    _catalog_inventory_report_artifact,
    # Helpers
    _artifact_not_found,
    _display_path,
    _table_columns,
    _select_expr,
    _artifact_cache_info,
    _public_url,
    _download_public_to_temp,
    _copy_gcs_to_temp,
    _resolved_artifact,
    _resolved_parquet,
    _resolved_json,
    _parquet_not_found,
    _json_not_found,
    _load_inventory_report,
    _inventory_source_status,
)

# ── External libs (monkeypatched by tests) ──────────────────────────────────

import requests  # noqa: E401 — exposed for test monkeypatching
from lab_connectors.http import HttpClient  # noqa: E401 — exposed for test monkeypatching

# ── Inventory queries ───────────────────────────────────────────────────────

from _inventory import (
    query_inventory,
    inventory_status,
    catalog_inventory_search,
    _source_radar_context,
    inventory_diff,
)

# ── Catalog signals ─────────────────────────────────────────────────────────

from _signals import (
    query_signals,
)

# ── Radar queries ───────────────────────────────────────────────────────────

from _radar import (
    radar_summary,
    radar_history,
    radar_status_md,
    radar_delta,
)

# ── Registry queries ────────────────────────────────────────────────────────

from _registry import (
    registry_query,
)

# ── Find by URL ─────────────────────────────────────────────────────────────

from _find_url import (
    find_by_url,
)

# ── URL probing ─────────────────────────────────────────────────────────────

from _probe import (
    probe_url,
    _guess_format,
)

# ── CKAN ────────────────────────────────────────────────────────────────────

from _ckan import (
    _ckan_package_show,
    _ckan_get_json,
    _ckan_action_endpoint,
)

# ── SPARQL ──────────────────────────────────────────────────────────────────

from _sparql import (
    _sparql_query_raw,
)

# ── HTML ────────────────────────────────────────────────────────────────────

from _html import (
    _html_extract_links,
    _extract_links_from_html,
)

# ── SDMX discovery ──────────────────────────────────────────────────────────

from _sdmx import (
    discover_sdmx,
    _read_sdmx_inventory_rows,
    _score_dataflow,
)

# ── Topic inference ─────────────────────────────────────────────────────────

from _topic import (
    infer_topic,
    _score_text_by_topics,
    _TOPIC_KEYWORDS,
)

# ── Source recommendation ───────────────────────────────────────────────────

from _recommend import (
    recommend_sources,
)
