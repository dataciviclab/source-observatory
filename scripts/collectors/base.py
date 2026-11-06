from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

USER_AGENT = "DataCivicLab-SourceObservatory/1.0"
DEFAULT_TIMEOUT_SECONDS = 60


@dataclass
class CollectorResult:
    rows: list[dict[str, Any]]
    warning: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    # Tracks whether the primary SSL attempt failed but fallback succeeded.
    # None means no fallback; True means fallback was used and succeeded.
    ssl_fallback_used: bool | None = None


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def inventory_cfg(source_cfg: dict[str, Any]) -> dict[str, Any]:
    """Legge il blocco `inventory:` dalla config della fonte nel registry."""
    inv = source_cfg.get("inventory")
    if isinstance(inv, dict):
        return inv
    return {}
