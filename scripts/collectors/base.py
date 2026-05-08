from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter


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


def get_observatory_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Connection": "close",
        }
    )
    return session


def get_pooled_session(pool_connections: int = 16, pool_maxsize: int = 32) -> requests.Session:
    """Session with HTTPAdapter connection pooling — reuse across calls."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    adapter = HTTPAdapter(pool_connections=pool_connections, pool_maxsize=pool_maxsize)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def observatory_get(
    url: str,
    *,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> requests.Response:
    request_headers = dict(headers or {})
    with get_observatory_session() as session:
        response = session.get(
            url,
            timeout=timeout,
            headers=request_headers or None,
            **kwargs,
        )
    return response


def observatory_head(
    url: str,
    *,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """HEAD request with SSL fallback: tries verify=True first, falls back to verify=False on SSLError."""
    from lab_connectors.http import HttpClient

    client = HttpClient(timeout=timeout, user_agent=USER_AGENT)
    result = client.head(url, headers=headers or {}, **kwargs)
    if result.is_ok:
        return result.response
    # Should not happen — observatory_head was used when we expected success
    raise result.err if result.err else RuntimeError(f"HEAD failed for {url}")


def strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


def sparql_binding_value(binding: dict[str, Any], name: str) -> str | None:
    value = (binding.get(name) or {}).get("value")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def compact_uri_name(uri: str | None) -> str | None:
    if not uri:
        return None
    value = uri.rstrip("/")
    if "#" in value:
        return value.rsplit("#", 1)[-1] or value
    return value.rsplit("/", 1)[-1] or value


def inventory_cfg(source_cfg: dict[str, Any]) -> dict[str, Any]:
    """Legge il blocco `inventory:` dalla config della fonte nel registry."""
    inv = source_cfg.get("inventory")
    if isinstance(inv, dict):
        return inv
    return {}
