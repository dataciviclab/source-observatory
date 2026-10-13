"""Portal profiling — probe leggero su portali HTML.

``probe_html_portal`` è SO-specifico (1 fonte, auto-discovery).
``fetch_sitemap_pages`` e ``fetch_robots_sitemaps`` sono in
``lab_connectors.discovery.portal`` — importati qui per backward compat.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from lab_connectors.discovery.portal import (  # noqa: F401
    PortalProfile,
    fetch_robots_sitemaps,
    fetch_sitemap_pages,
)
from lab_connectors.http import HttpClient


def _scan_html_for_rss(html: str) -> list[dict[str, str]]:
    """Cerca link a feed RSS/Atom nell'HTML della homepage."""
    feeds: list[dict[str, str]] = []
    pattern = re.compile(
        r'<link\s[^>]*?rel=["\']alternate["\'][^>]*?'
        r'type=["\']application/(?:rss|atom)\+xml["\'][^>]*?'
        r'href=["\']([^"\']+)["\'][^>]*?'
        r'(?:title=["\']([^"\']*)["\'])?',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        feeds.append({"url": match.group(1), "title": match.group(2) or ""})
    return feeds


def _scan_html_for_jsonapi(html: str, base_url: str, *, timeout: int = 5) -> bool:
    """Rileva pattern JSON:API (Drupal) nell'HTML o nell'URL."""
    if "jsonapi" in html.lower():
        return True
    parsed = urlparse(base_url)
    test_url = f"{parsed.scheme}://{parsed.netloc}/jsonapi"
    client = HttpClient(timeout=timeout)
    result = client.get(test_url)
    if result.is_ok and result.response and result.response.status_code < 400:
        content_type = (result.response.headers.get("Content-Type") or "").lower()
        if "json" in content_type or "api" in content_type:
            return True
    return False


def probe_html_portal(
    base_url: str,
    *,
    timeout: int = 10,
    fetch_sitemap: bool = True,
    fetch_homepage: bool = True,
) -> PortalProfile:
    """Probe leggero su un portale HTML per scoprire struttura e pagine.

    Esegue probe a costo fisso (nessun crawl):
    1. ``/robots.txt`` → estrae URL delle sitemap
    2. Sitemap XML → lista pagine del portale
    3. Homepage → cerca feed RSS e pattern JSON:API (Drupal)

    Args:
        base_url: URL base del portale.
        timeout: Timeout HTTP per ogni chiamata.
        fetch_sitemap: Se True, scarica e parse le sitemap trovate.
        fetch_homepage: Se True, scarica la homepage per RSS/API detection.

    Returns:
        PortalProfile con tutto ciò che è stato scoperto.
    """
    profile = PortalProfile(base_url=base_url)

    parsed = urlparse(base_url)
    domain_root = f"{parsed.scheme}://{parsed.netloc}"
    _probe_targets = list(dict.fromkeys([base_url.rstrip("/"), domain_root]))

    # 1. robots.txt → sitemap
    sitemap_urls: list[str] = []
    for target in _probe_targets:
        has_robots, urls = fetch_robots_sitemaps(target, timeout=timeout)
        if has_robots:
            profile.has_robots_txt = True
        for u in urls:
            if u not in sitemap_urls:
                sitemap_urls.append(u)

    # 2. Sitemap nei path canonici
    _common_sitemap_paths = [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/opendata/sitemap.xml",
    ]
    for target in _probe_targets:
        for sm_path in _common_sitemap_paths:
            sm_url = urljoin(target + "/", sm_path.lstrip("/"))
            if sm_url in sitemap_urls:
                continue
            pages = fetch_sitemap_pages(sm_url, timeout=timeout)
            if pages:
                sitemap_urls.append(sm_url)
                profile.sitemap_pages.extend(pages)

    profile.sitemap_urls = list(dict.fromkeys(sitemap_urls))

    # 3. Fetch sitemap da robots.txt non ancora parse
    if fetch_sitemap:
        for sm_url in sitemap_urls:
            if sm_url not in _common_sitemap_paths:
                pages = fetch_sitemap_pages(sm_url, timeout=timeout)
                for p in pages:
                    if p not in profile.sitemap_pages:
                        profile.sitemap_pages.append(p)

    profile.sitemap_pages = list(dict.fromkeys(profile.sitemap_pages))

    # 4. Homepage → RSS + JSON:API + link interni
    if fetch_homepage:
        try:
            client = HttpClient(timeout=timeout)
            result = client.get(base_url)
            if result.is_ok and result.response is not None:
                html = result.response.text
                profile.rss_feeds = _scan_html_for_rss(html)
                profile.has_json_api = _scan_html_for_jsonapi(html, base_url)

                from html.parser import HTMLParser

                class _InternalLinkCounter(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.count = 0
                        self._domain = parsed.netloc.lower()

                    def handle_starttag(self, tag, attrs):
                        if tag.lower() != "a":
                            return
                        for key, value in attrs:
                            if key.lower() == "href" and value:
                                href = value.strip()
                                if href and not href.startswith(
                                    ("#", "mailto:", "tel:", "javascript:")
                                ):
                                    full = urljoin(base_url, href)
                                    if self._domain in urlparse(full).netloc.lower():
                                        self.count += 1
                                return

                parser = _InternalLinkCounter()
                parser.feed(html)
                profile.homepage_links = parser.count
        except Exception:
            pass

    return profile
