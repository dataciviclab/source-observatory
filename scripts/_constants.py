"""Costanti condivise tra gli script di source-observatory."""

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Registry ──────────────────────────────────────────────────────────────────
REGISTRY_PATH = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"

# ── Radar (scripts/radar_check.py → mcp/_radar.py) ───────────────────────────
RADAR_SUMMARY_PATH = REPO_ROOT / "data" / "radar" / "radar_summary.json"
RADAR_HISTORY_PATH = REPO_ROOT / "data" / "radar" / "radar_history.json"
STATUS_MD_PATH = REPO_ROOT / "data" / "radar" / "STATUS.md"

# ── Catalog inventory (scripts/build_catalog_inventory.py → mcp/_inventory.py) ─
CATALOG_INVENTORY_DIR_PATH = REPO_ROOT / "data" / "catalog_inventory" / "generated"
INVENTORY_PARQUET_PATH = CATALOG_INVENTORY_DIR_PATH / "catalog_inventory_latest.parquet"
CATALOG_INVENTORY_REPORT_PATH = CATALOG_INVENTORY_DIR_PATH / "catalog_inventory_report.json"
CATALOG_WATCH_REPORT_PATH = REPO_ROOT / "data" / "catalog" / "CATALOG_WATCH_REPORT.md"

# ── Source check (scripts/bulk_source_check.py → mcp/_signals.py) ────────────
CHECK_PARQUET_PATH = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "source_check_results.parquet"
CATALOG_SIGNALS_PATH = REPO_ROOT / "data" / "catalog" / "catalog_signals.json"

# ── Schemas (scripts/build_catalog_signals.py) ────────────────────────────────
SCHEMA_DIR_PATH = REPO_ROOT / "schemas"

# Canonical stale_reason taxonomy for catalog-inventory error classification.
# Used by build_catalog_inventory.py to tag stale rows.
STALE_REASON_TAGS = {
    "source_500": "HTTP 500 — Internal Server Error",
    "source_503": "HTTP 503 — Service Unavailable",
    "timeout": "Connection or application timeout",
    "ssl_error": "SSL/TLS handshake failure",
    "connection_error": "TCP connection failed",
    "dns_error": "DNS resolution failed",
    "unknown": "Unclassified error",
}


def stale_reason_from_exception(exc: Exception) -> str:
    """Map an exception to a canonical stale_reason tag."""
    msg = str(exc).lower()
    if "500" in msg or "internal server error" in msg:
        return "source_500"
    if "503" in msg or "service unavailable" in msg:
        return "source_503"
    if "connecttimeout" in msg or "connection timed out" in msg or "timed out" in msg:
        return "timeout"
    if "ssl_error" in msg or "sslv3" in msg or "tls" in msg or "ssl" in msg:
        return "ssl_error"
    if "connection error" in msg or "connectionerror" in msg or "connect" in msg:
        return "connection_error"
    if "resolution error" in msg or "resolutionerror" in msg or "name or service not known" in msg or "getaddrinfo" in msg:
        return "dns_error"
    return "unknown"


# Alias for backwards compatibility
ERROR_TAGS = STALE_REASON_TAGS


def load_radar_history(path: Path | None = None) -> dict:
    """Load radar history JSON. Returns empty dict if file missing."""
    p = path or RADAR_HISTORY_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_radar_history(history: dict, path: Path | None = None) -> None:
    """Save radar history JSON."""
    p = path or RADAR_HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_radar_probe(history: dict, probe_date: str, sources: list[dict]) -> dict:
    """Append a probe result to radar history, keeping last 14 days."""
    if "probes" not in history:
        history["probes"] = []

    history["probes"].append({
        "probe_date": probe_date,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
    })

    # Keep only last 14 days
    cutoff = len(history["probes"]) - 14
    if cutoff > 0:
        history["probes"] = history["probes"][cutoff:]

    return history


def load_registry(path: Path | None = None) -> dict:
    """Load sources registry YAML. Defaults to REGISTRY_PATH."""
    import yaml

    p = path or REGISTRY_PATH
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Registry YAML at {p} must contain a top-level mapping.")
    return data


def save_registry(path: Path | None, registry: dict) -> None:
    """Save registry YAML. Defaults to REGISTRY_PATH."""
    import yaml

    p = path or REGISTRY_PATH
    with p.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(registry, fh, sort_keys=False, allow_unicode=True)
