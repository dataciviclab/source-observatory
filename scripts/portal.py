"""Portal profiling — probe leggero su portali HTML.

Tutto SO-specifico: usato solo dal collector HTML in modalità
discovery=auto (1 fonte: opencivitas). Nessun altro consumer nel Lab.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from lab_connectors.http import HttpClient


@dataclass
class PortalProfile:
    """Profilo leggero di un portale HTML, ottenuto via probe senza crawl.

    Attributes:
        base_url: URL base del portale.
        has_robots_txt: ``/robots.txt`` raggiungibile.
        sitemap_urls: URLs delle sitemap trovate in robots.txt.
        sitemap_pages: URLs delle pagine estratte dalla sitemap.
        rss_feeds: Feed RSS trovati nell'HTML della homepage.
        has_json_api: Pattern JSON:API rilevato (es. Drupal).
        homepage_links: Numero di link interni nella homepage.
    """

    base_url: str
    has_robots_txt: bool = False
    sitemap_urls: list[str] = field(default_factory=list)
    sitemap_pages: list[str] = field(default_factory=list)
    rss_feeds: list[dict[str, str]] = field(default_factory=list)
    has_json_api: bool = False
    homepage_links: int = 0


def fetch_robots_sitemaps(base_url: str, *, timeout: int = 10) -> tuple[bool, list[str]]:
    """Probe ``/robots.txt`` e estrae direttive ``Sitemap:``.

    Returns:
        (raggiungibile, lista URL sitemap)
    """
    robots_url = urljoin(base_url + "/", "robots.txt")
    client = HttpClient(timeout=timeout)
    result = client.get(robots_url)
    if not result.is_ok or result.response is None or result.response.status_code >= 400:
        return False, []

    sitemaps: list[str] = []
    for line in result.response.text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            url = line.split(":", 1)[1].strip()
            if url:
                sitemaps.append(url)
    return True, sitemaps


def fetch_sitemap_pages(sitemap_url: str, *, timeout: int = 10) -> list[str]:
    """Fetch e parse una sitemap XML, ritorna lista di URL delle pagine.

    Supporta sia sitemap standard (``<url><loc>``) che sitemap index
    (``<sitemapindex><sitemap><loc>``). In caso di sitemap index, segue
    ricorsivamente le sotto-sitemap (max 10 depth, max 50 sub-sitemaps).

    Args:
        sitemap_url: URL della sitemap (es. ``https://example.gov.it/sitemap.xml``).
        timeout: Timeout HTTP.

    Returns:
        Lista di URL delle pagine trovate nella sitemap.
        Lista vuota se sitemap non raggiungibile o malformata.
    """
    return _fetch_sitemap_recursive(sitemap_url, timeout=timeout, depth=0)


def _fetch_sitemap_recursive(
    sitemap_url: str, *, timeout: int, depth: int, max_depth: int = 10
) -> list[str]:
    """Fetch e parse ricorsivo di sitemap, con protezione profondità."""
    if depth >= max_depth:
        return []

    client = HttpClient(timeout=timeout)
    result = client.get(sitemap_url)
    if not result.is_ok or result.response is None or result.response.status_code >= 400:
        return []

    try:
        root = ET.fromstring(result.response.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        is_index = root.tag.endswith("sitemapindex")

        if is_index:
            sub_sitemaps: list[str] = []
            for sm_elem in root.findall(".//sm:sitemap", ns):
                loc = sm_elem.find("sm:loc", ns)
                if loc is not None and loc.text:
                    sub_sitemaps.append(loc.text.strip())
            if not sub_sitemaps:
                for sm_elem in root.findall(".//sitemap"):
                    loc = sm_elem.find("loc")
                    if loc is not None and loc.text:
                        sub_sitemaps.append(loc.text.strip())

            all_urls: list[str] = []
            for sub_url in sub_sitemaps[:50]:
                all_urls.extend(_fetch_sitemap_recursive(sub_url, timeout=timeout, depth=depth + 1))
            return all_urls
        else:
            urls: list[str] = []
            for url_elem in root.findall(".//sm:url", ns):
                loc = url_elem.find("sm:loc", ns)
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())
            if not urls:
                for url_elem in root.findall(".//url"):
                    loc = url_elem.find("loc")
                    if loc is not None and loc.text:
                        urls.append(loc.text.strip())
            return urls
    except Exception:
        return []


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
