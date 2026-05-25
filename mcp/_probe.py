"""URL probing: reachability, content-type, format detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import _artifact
from lab_connectors.http import HttpClient


def _guess_format(url: str, content_type: str | None) -> str | None:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type in _artifact._FORMAT_BY_CONTENT_TYPE:
        return _artifact._FORMAT_BY_CONTENT_TYPE[media_type]

    suffix = Path(urlparse(url).path).suffix.lower()
    return _artifact._FORMAT_BY_SUFFIX.get(suffix)


def probe_url(url: str, timeout: int = 15) -> dict[str, Any]:
    """Probe a single URL with HEAD and a small GET fallback."""
    clean_url = (url or "").strip()
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "url": clean_url,
            "http_status": None,
            "content_type": None,
            "format": None,
            "size": None,
            "is_reachable": False,
            "error": "invalid_url",
        }

    safe_timeout = max(1, min(int(timeout or 15), 60))

    ssl_used: bool | None = None

    # Attempt 1: HEAD via HttpClient (SSL fallback built-in)
    client = HttpClient(timeout=safe_timeout)
    result = client.head(clean_url)

    if result.is_ok:
        response = result.response
        ssl_used = result.ssl_fallback_used
    elif result.is_ssl_fallback_failed:
        return {
            "url": clean_url,
            "http_status": None,
            "content_type": None,
            "format": _guess_format(clean_url, None),
            "size": None,
            "is_reachable": False,
            "error": "ssl_fallback_failed",
            "message": str(result.err)[:200],
        }
    elif result.ssl_fallback_used and result.response is not None:
        response = result.response
        ssl_used = True
    elif result.err is not None:
        result2 = client.get(
            clean_url,
            headers={"Range": "bytes=0-0"},
        )
        if result2.is_ok:
            response = result2.response
            ssl_used = result2.ssl_fallback_used
        elif result2.is_ssl_fallback_failed:
            return {
                "url": clean_url,
                "http_status": None,
                "content_type": None,
                "format": _guess_format(clean_url, None),
                "size": None,
                "is_reachable": False,
                "error": "ssl_fallback_failed",
                "message": str(result2.err)[:200],
            }
        elif result2.ssl_fallback_used and result2.response is not None:
            response = result2.response
            ssl_used = True
        else:
            return {
                "url": clean_url,
                "http_status": None,
                "content_type": None,
                "format": _guess_format(clean_url, None),
                "size": None,
                "is_reachable": False,
                "error": type(result2.err).__name__,
                "message": str(result2.err)[:200],
            }
    else:
        return {
            "url": clean_url,
            "http_status": None,
            "content_type": None,
            "format": _guess_format(clean_url, None),
            "size": None,
            "is_reachable": False,
            "error": "unknown_error",
            "message": "unexpected state in probe_url",
        }

    content_type = response.headers.get("content-type")
    content_length = response.headers.get("content-length")
    try:
        size = int(content_length) if content_length is not None else None
    except ValueError:
        size = None

    return {
        "url": clean_url,
        "http_status": response.status_code,
        "content_type": content_type,
        "format": _guess_format(clean_url, content_type),
        "size": size,
        "is_reachable": response.status_code < 400,
        "ssl_fallback_used": ssl_used,
    }
