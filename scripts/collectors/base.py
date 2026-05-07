from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning


USER_AGENT = "DataCivicLab-SourceObservatory/1.0"
DEFAULT_TIMEOUT_SECONDS = 60


class SslFallbackFailed(Exception):
    """Raised when both the SSL attempt and the fallback (verify=False) fail."""

    def __init__(self, ssl_error: requests.exceptions.SSLError, fallback_error: requests.exceptions.RequestException):
        self.ssl_error = ssl_error
        self.fallback_error = fallback_error
        super().__init__(f"SSL failed ({ssl_error}) then fallback failed ({fallback_error})")


@dataclass
class CollectorResult:
    rows: list[dict[str, Any]]
    warning: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None


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


def observatory_ssl_fallback_get(
    url: str,
    *,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> tuple[requests.Response | None, Exception | bool | None]:
    """Get with SSL fallback: tries verify=True first, falls back to verify=False on SSLError.

    Returns (response, exc):
    - (response, None): primary GET succeeded
    - (response, True): primary SSL failed, fallback with verify=False succeeded
    - (None, Exception): both attempts failed — exc carries the final error
    """
    request_headers = dict(headers or {})
    try:
        with get_observatory_session() as session:
            response = session.get(
                url,
                timeout=timeout,
                headers=request_headers or None,
                **kwargs,
            )
        return response, None
    except requests.exceptions.SSLError as exc:
        urllib3.disable_warnings(category=InsecureRequestWarning)
        try:
            with requests.Session() as session:
                session.headers.update({"User-Agent": USER_AGENT})
                response = session.get(
                    url,
                    timeout=timeout,
                    headers=request_headers or None,
                    verify=False,
                    **kwargs,
                )
            return response, True  # SSL fallback was used and succeeded
        except requests.exceptions.RequestException as fallback_exc:
            return None, SslFallbackFailed(ssl_error=exc, fallback_error=fallback_exc)


def observatory_head(
    url: str,
    *,
    timeout: int | float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """HEAD request with SSL fallback: tries verify=True first, falls back to verify=False on SSLError."""
    request_headers = dict(headers or {})
    try:
        with get_observatory_session() as session:
            response = session.head(
                url,
                timeout=timeout,
                headers=request_headers or None,
                allow_redirects=True,
                **kwargs,
            )
        return response
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(category=InsecureRequestWarning)
        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT})
            return session.head(
                url,
                timeout=timeout,
                headers=request_headers or None,
                allow_redirects=True,
                verify=False,
                **kwargs,
            )


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
