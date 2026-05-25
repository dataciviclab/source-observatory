"""HTML link extraction for SO MCP."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from lab_connectors.http import HttpClient


def _extract_links_from_html(html: str, base_url: str) -> list[dict[str, Any]]:
    """Extract data download links from raw HTML.

    Returns list of {url, format, title}.
    """
    DATA_EXTENSIONS = {".csv", ".json", ".xlsx", ".xls", ".ods", ".zip", ".xml", ".geojson"}
    from html.parser import HTMLParser

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: list[dict[str, str]] = []

        def handle_starttag(self, tag, attrs):
            if tag not in ("a", "area"):
                return
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "") or attrs_dict.get("xlink:href", "")
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                return
            full_url = urljoin(base_url, href)
            lower = full_url.lower()
            fmt = None
            for ext in DATA_EXTENSIONS:
                if ext in lower:
                    fmt = ext.lstrip(".").upper()
                    if fmt == "GEOJSON":
                        fmt = "GEOJSON"
                    break
            if not fmt:
                return
            title = (attrs_dict.get("aria-label") or attrs_dict.get("title") or "").strip()
            self.links.append({"url": full_url, "format": fmt, "title": title})

    parser = Parser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.links


def _html_extract_links(url: str, timeout: int = 20) -> dict[str, Any]:
    """Extract file download links from an HTML page.

    Returns {url, links: [{url, format, title}], total, content_type, is_reachable}.
    Uses HttpClient with SSL fallback built-in.
    """
    if not url:
        return {"error": "invalid_url", "message": "url is required"}
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"error": "invalid_url", "message": f"Invalid URL: {url}"}

    safe_timeout = max(1, min(int(timeout or 20), 60))
    client = HttpClient(timeout=safe_timeout)
    result = client.get(url)

    if not result.is_ok:
        return {
            "url": url,
            "is_reachable": False,
            "error": type(result.err).__name__,
            "message": str(result.err)[:200],
        }

    response = result.response
    content_type = response.headers.get("content-type", "")

    text_html = "text/html" in content_type.lower()
    try:
        html_text = response.text if text_html else ""
    except Exception:
        html_text = ""

    links = _extract_links_from_html(html_text, url) if text_html else []

    return {
        "url": url,
        "is_reachable": response.status_code < 400,
        "http_status": response.status_code,
        "content_type": content_type,
        "links": links,
        "total": len(links),
        "formats": sorted({link["format"] for link in links}),
        "ssl_fallback_used": result.ssl_fallback_used,
    }
