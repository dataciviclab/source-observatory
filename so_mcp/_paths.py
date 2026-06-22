"""
Canonical artifact paths for SO artifacts.

Separated from ``scripts/_constants.py`` so that ``so_mcp/`` modules
can import path constants without a ``sys.path`` hack.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Registry ──────────────────────────────────────────────────────────────────
REGISTRY_PATH = _REPO_ROOT / "data" / "radar" / "sources_registry.yaml"

# ── Radar (scripts/radar_check.py → so_mcp/_radar.py) ────────────────────────
RADAR_SUMMARY_PATH = _REPO_ROOT / "data" / "radar" / "radar_summary.json"
RADAR_HISTORY_PATH = _REPO_ROOT / "data" / "radar" / "radar_history.json"
STATUS_MD_PATH = _REPO_ROOT / "data" / "radar" / "STATUS.md"

# ── Catalog inventory (scripts/build_catalog_inventory.py → so_mcp/_inventory.py) ─
CATALOG_INVENTORY_DIR_PATH = _REPO_ROOT / "data" / "catalog_inventory" / "generated"
INVENTORY_PARQUET_PATH = CATALOG_INVENTORY_DIR_PATH / "catalog_inventory_latest.parquet"
CATALOG_INVENTORY_REPORT_PATH = CATALOG_INVENTORY_DIR_PATH / "catalog_inventory_report.json"

# ── Source check (scripts/bulk_source_check.py → so_mcp/_signals.py) ─────────
CHECK_PARQUET_PATH = (
    _REPO_ROOT / "data" / "catalog_inventory" / "generated" / "source_check_results.parquet"
)
CATALOG_SIGNALS_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_signals.json"

# ── Health scores (scripts/build_compliance_scores.py → data-advocacy) ────────
OPEN_DATA_HEALTH_SCORES_PATH = _REPO_ROOT / "data" / "health" / "open_data_health_scores.json"
