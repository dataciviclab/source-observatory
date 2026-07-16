"""
Canonical artifact paths for SO artifacts.

Fonte unica per tutti i path del repo. ``scripts/_constants.py`` re-esporta
da qui. I moduli ``so_mcp/`` importano direttamente.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Registry ──────────────────────────────────────────────────────────────────
REGISTRY_PATH = _REPO_ROOT / "data" / "radar" / "sources_registry.yaml"

# ── Radar ─────────────────────────────────────────────────────────────────────
RADAR_SUMMARY_PATH = _REPO_ROOT / "data" / "radar" / "radar_summary.json"
RADAR_HISTORY_PATH = _REPO_ROOT / "data" / "radar" / "radar_history.json"
STATUS_MD_PATH = _REPO_ROOT / "data" / "radar" / "STATUS.md"

# ── Catalog inventory ─────────────────────────────────────────────────────────
CATALOG_INVENTORY_DIR_PATH = _REPO_ROOT / "data" / "catalog_inventory" / "generated"
INVENTORY_PARQUET_PATH = CATALOG_INVENTORY_DIR_PATH / "catalog_inventory_latest.parquet"
CATALOG_INVENTORY_REPORT_PATH = CATALOG_INVENTORY_DIR_PATH / "catalog_inventory_report.json"
CHECK_PARQUET_PATH = CATALOG_INVENTORY_DIR_PATH / "source_check_results.parquet"

# ── Signals ───────────────────────────────────────────────────────────────────
CATALOG_SIGNALS_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_signals.json"

# ── Source reports (CI, weekly) ───────────────────────────────────────────────
SOURCE_REPORTS_DIR = _REPO_ROOT / "data" / "reports" / "source_reports"
DASHBOARD_PATH = _REPO_ROOT / "data" / "reports" / "sources_dashboard.json"

# ── Schemas ───────────────────────────────────────────────────────────────────
SCHEMA_DIR_PATH = _REPO_ROOT / "schemas"
