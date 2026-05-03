"""HTML portal collector — CSV Magnet scan for portals without structured API.

Phase 2 della pipeline SO: quick survey per portali HTML senza API catalog.

Strategia:
  - Se sitemap_url: parse sitemap → campione N pagine → infer pattern → estimate
  - Se area_pages: fetch diretto di ogni area page → link data diretti

Output:
  - rows: [{url, format, prefix, year_signal, topic, landing_page}] — per source-check
  - summary: {total_links_estimate, by_format, prefix_matrix, series, topics, method}

Non fa full crawl (191 pagine). Campiona per stimare.

Uso:
    from collectors.html import collect
    result = collect("dati_salute", source_cfg, captured_at)
"""

from __future__ import annotations

import random
import re
import time
from collections import Counter
from typing import Any
from urllib.parse import urljoin

from .base import CollectorResult, observatory_ssl_fallback_get


DATA_EXTENSIONS = {".csv", ".json", ".xlsx", ".xls", ".ods", ".zip", ".xml", ".geojson"}

# ─── HTML Parsing ──────────────────────────────────────────────────────────────


_DATA_TITLE_RE = None  # lazycompiled


def _extract_page_meta(html: str) -> dict[str, str]:
    """Estrae metadata significativi da una pagina HTML (title, modified, description).

    Supporta:
    - <meta name="gatsby:title"> (Gatsby/Drupal pattern)
    - <title> plain
    - <meta name="description">
    - data items con schema.org Dataset (per portali open data strutturati)
    """
    global _DATA_TITLE_RE
    if _DATA_TITLE_RE is None:
        _DATA_TITLE_RE = re.compile(r'<title[^>]*>([^<]+)</title>', re.IGNORECASE)

    meta: dict[str, str] = {}

    # Try gatsby:title (priority — it's the canonical page title for open data portals)
    gatsby_title = re.search(r'<meta\s+(?:name|data-gatsby-head)=["\']gatsby:title["\']\s+content=["\']([^"\']+)["\']', html)
    if gatsby_title:
        meta["title"] = gatsby_title.group(1).strip()

    # Fallback to <title>
    if "title" not in meta:
        m = _DATA_TITLE_RE.search(html)
        if m:
            raw = m.group(1).strip()
            # Strip common prefix pattern "Open Data - "
            if raw.startswith("Open Data - "):
                raw = raw[12:]
            meta["title"] = raw

    # Description
    desc = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if desc:
        meta["description"] = desc.group(1).strip()[:200]

    return meta


class _DataLinksParser:
    """Estrae link a file data da HTML già scaricato."""

    def __init__(self, base_url: str, html: str):
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
        self.links = parser.links


# ─── URL Analysis ─────────────────────────────────────────────────────────────


_PREFIX_RE = re.compile(r"^([A-Z0-9]{2,8})")
_YEAR_RE = re.compile(r"(20[12]\d)")


def _extract_prefix(filename: str) -> str:
    """Estrae prefisso categoriale dal filename (prima underscore o run di maiuscole)."""
    # FRM_FARMA_5_20260427.csv → FRM
    # SCUANAGRAFESTAT202526 → SCUANAGRAFESTAT
    if "_" in filename:
        return filename.split("_")[0]
    m = _PREFIX_RE.match(filename)
    if m:
        return m.group(1)
    return filename[:6]


def _extract_years(filename: str) -> list[int]:
    """Estrae tutti i year signal (20xx) presenti nel filename."""
    return [int(y) for y in _YEAR_RE.findall(filename)]


_TOPIC_SIGNALS: dict[str, list[str]] = {
    "sanita": ["salute", "ospedal", "medic", "farmaci", "dispositivi", "serd", "dsm"],
    "trasporti": ["trasport", "mobilita", "traffico", "aeroport", "porto"],
    "ambiente": ["ambiente", "rischio", "dissesto", "acqua", "rifiuti", "energia"],
    "economia": ["economia", "lavoro", "imprese", "commercio", "mercato"],
    "istruzione": ["scuola", "universita", "istruzione", "alunni", "studenti", "personale"],
    "cultura": ["cultura", "museo", "patrimonio", "turismo"],
    "territorio": ["territorio", "urban", "comune", "regione", "provincia", "catasto"],
    "agricoltura": ["agricoltura", "agri", "allevamento", "produzione"],
    "finanza": ["bilancio", "finanza", "tesoro", "preconsuntivo"],
}


def _guess_topic(url: str, topic_hint: str | None) -> str:
    if topic_hint:
        return topic_hint
    url_lower = url.lower()
    for topic, signals in _TOPIC_SIGNALS.items():
        if any(s in url_lower for s in signals):
            return topic
    return "unknown"


# ─── Sitemap Helper ───────────────────────────────────────────────────────────


def _fetch_sitemap(sitemap_url: str, timeout: int = 15) -> tuple[list[str] | None, str | None]:
    """Fetch e parse sitemap XML, ritorna lista di <loc> URL."""
    import xml.etree.ElementTree as ET

    try:
        response, exc = observatory_ssl_fallback_get(sitemap_url, timeout=timeout)
        if response is None:
            return None, str(exc)
        if response.status_code >= 400:
            return None, f"HTTP {response.status_code}"
        root = ET.fromstring(response.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = []
        for url_elem in root.findall("sm:url", ns):
            loc = url_elem.find("sm:loc", ns)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        if not urls:
            for url_elem in root.findall(".//url"):
                loc = url_elem.find("loc")
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())
        return urls, None
    except Exception as e:
        return None, str(e)


# ─── Core Scan ───────────────────────────────────────────────────────────────


def _scan_sitemap(
    sitemap_url: str,
    topic_hint: str | None,
    source_id: str,
    base_url: str,
    *,
    sample_pages: int = 30,
    page_delay: float = 0.2,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Scan un portale HTML via sitemap con quick sample.

    1. Parse sitemap → dataset page URLs
    2. Campiona N pagine direttamente dal sitemap
    3. Fetch sample → estrae data link pattern
    4. Stima total links dal sample

    Returns:
        summary dict, rows list
    """
    sitemap_urls, sitemap_err = _fetch_sitemap(sitemap_url)
    if sitemap_err or sitemap_urls is None:
        return {"error": f"sitemap failed: {sitemap_err}"}, []

    dataset_signals = ("/it/dataset/", "/dataset/", "/dati/", "/open-data/", "/opendata/", "/catalogo/")
    dataset_page_urls = [
        u for u in sitemap_urls
        if any(s in u.lower() for s in dataset_signals)
    ]

    if not dataset_page_urls:
        return {"error": "no dataset pages found in sitemap"}, []

    total_pages = len(dataset_page_urls)

    # Sample N pages directly from sitemap
    sampled = list(dataset_page_urls[:])  # copy
    random.shuffle(sampled)
    sample_size = min(sample_pages, len(sampled))
    sampled = sampled[:sample_size]

    all_data_links: list[dict[str, str]] = []
    seen_data_urls: set[str] = set()
    pages_probed = 0
    page_meta: dict[str, dict[str, str]] = {}  # page_url → {title, description}

    for page_url in sampled:
        time.sleep(page_delay)
        # Fetch page directly — no separate HEAD probe (saves one round-trip)
        response, page_err = observatory_ssl_fallback_get(page_url, timeout=10)
        if page_err or response is None:
            continue
        pages_probed += 1

        # Extract page metadata (title, description) for enrichment
        page_meta[page_url] = _extract_page_meta(response.text)

        parser = _DataLinksParser(page_url, response.text)
        for link in parser.links:
            if link["url"] not in seen_data_urls:
                seen_data_urls.add(link["url"])
                link["_page_url"] = page_url  # track provenance for metadata enrichment
                all_data_links.append(link)

    # Dedup by (url, format) — use frozenset as dict key, track separately
    seen_url_formats: set[tuple[str, str]] = set()
    deduped_links: list[dict[str, str]] = []
    for link in all_data_links:
        key = (link["url"], link.get("format") or "")
        if key not in seen_url_formats:
            seen_url_formats.add(key)
            deduped_links.append(link)
    all_data_links = deduped_links

    prefix_matrix: dict[str, int] = {}
    by_format: dict[str, int] = {}
    years_set: set[int] = set()
    series: dict[str, dict[str, Any]] = {}

    for link in all_data_links:
        url = link["url"]
        filename = url.split("/")[-1].rsplit(".", 1)[0]
        prefix = _extract_prefix(filename)
        prefix_matrix[prefix] = prefix_matrix.get(prefix, 0) + 1

        fmt = link.get("format", "?")
        by_format[fmt] = by_format.get(fmt, 0) + 1

        years = _extract_years(filename)
        for y in years:
            years_set.add(y)

        if prefix not in series:
            series[prefix] = {"years": set(), "count": 0, "sample": filename}
        series[prefix]["count"] += 1
        for y in years:
            series[prefix]["years"].add(y)

    # Estimate total from sample
    links_per_page = len(all_data_links) / pages_probed if pages_probed > 0 else 0
    estimated_total = int(links_per_page * total_pages)

    series_serializable = {}
    for prefix, info in series.items():
        series_serializable[prefix] = {
            "years": sorted(list(info["years"])),
            "count": info["count"],
            "sample": info["sample"],
        }

    # Rows: uno per data link URL — per source-check
    rows = []
    for link in all_data_links:
        url = link["url"]
        filename = url.split("/")[-1].rsplit(".", 1)[0]
        prefix = _extract_prefix(filename)
        years = _extract_years(filename)
        topic = _guess_topic(url, topic_hint)
        item_id = filename[:100]  # truncate per safety

        # Enrich from page metadata (provenance-aware)
        data_page_url: str | None = link.get("_page_url")
        page_meta_row = page_meta.get(data_page_url) if data_page_url else {}
        page_title = page_meta_row.get("title") if page_meta_row else None

        rows.append({
            # canonical columns (per bulk_source_check e inventario)
            "source_id": source_id,
            "source_kind": "catalog",
            "protocol": "html",
            "source_url": base_url,
            "item_id": item_id,
            "item_name": prefix,
            "item_slug": item_id,
            "title": page_title or f"{prefix} {topic}",
            "organization": None,
            "tags": None,
            "notes_excerpt": page_meta_row.get("description") if page_meta_row else None,
            "landing_page": data_page_url,
            "distribution_url": url,
            "datastore_active": False,
            "resource_count": 1,
            "issued": None,
            "modified": None,
            # custom columns (informative per csv_magnet)
            "url": url,
            "format": link.get("format", "?"),
            "prefix": prefix,
            "year_signal": years[0] if years else None,
            "topic": topic,
        })

    summary = {
        "total_links_estimate": estimated_total,
        "total_pages_in_sitemap": total_pages,
        "pages_probed": pages_probed,
        "pages_sampled": sample_size,
        "links_found_in_sample": len(all_data_links),
        "links_per_page_estimate": round(links_per_page, 2),
        "by_format": by_format,
        "prefix_matrix": prefix_matrix,
        "series": series_serializable,
        "years_range": [min(years_set), max(years_set)] if years_set else [],
        "topics": dict(Counter(_guess_topic(link["url"], topic_hint) for link in all_data_links)),
        "method": "csv_magnet_sitemap_sample",
    }

    return summary, rows


def _scan_area_pages(
    area_pages: list[str],
    topic_hint: str | None,
    source_id: str,
    base_url: str,
    *,
    page_delay: float = 0.2,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Scan portale HTML via area_pages (nessun second-level crawl).

    Fetch ogni area page direttamente → estrae tutti i link data.
    Tutto il contenido è sulla pagina area, no pagine figlie.

    Returns:
        summary dict, rows list
    """
    all_data_links: list[dict[str, str]] = []
    seen_data_urls: set[str] = set()

    for area_url in area_pages:
        time.sleep(page_delay)
        response, err = observatory_ssl_fallback_get(area_url, timeout=15)
        if err or response is None:
            continue
        parser = _DataLinksParser(area_url, response.text)
        for link in parser.links:
            if link["url"] not in seen_data_urls:
                seen_data_urls.add(link["url"])
                all_data_links.append(link)

    # Stats
    prefix_matrix: dict[str, int] = {}
    by_format: dict[str, int] = {}
    years_set: set[int] = set()
    series: dict[str, dict[str, Any]] = {}

    for link in all_data_links:
        url = link["url"]
        filename = url.split("/")[-1].rsplit(".", 1)[0]
        prefix = _extract_prefix(filename)
        prefix_matrix[prefix] = prefix_matrix.get(prefix, 0) + 1

        fmt = link.get("format", "?")
        by_format[fmt] = by_format.get(fmt, 0) + 1

        years = _extract_years(filename)
        for y in years:
            years_set.add(y)

        if prefix not in series:
            series[prefix] = {"years": set(), "count": 0, "sample": filename}
        series[prefix]["count"] += 1
        for y in years:
            series[prefix]["years"].add(y)

    series_serializable = {}
    for prefix, info in series.items():
        series_serializable[prefix] = {
            "years": sorted(list(info["years"])),
            "count": info["count"],
            "sample": info["sample"],
        }

    # Rows for source-check
    rows = []
    for link in all_data_links:
        url = link["url"]
        filename = url.split("/")[-1].rsplit(".", 1)[0]
        prefix = _extract_prefix(filename)
        years = _extract_years(filename)
        topic = _guess_topic(url, topic_hint)
        item_id = filename[:100]
        rows.append({
            # canonical columns
            "source_id": source_id,
            "source_kind": "catalog",
            "protocol": "html",
            "source_url": base_url,
            "item_id": item_id,
            "item_name": prefix,
            "item_slug": item_id,
            "title": f"{prefix} {topic}",
            "organization": None,
            "tags": None,
            "notes_excerpt": None,
            "landing_page": None,
            "distribution_url": url,
            "datastore_active": False,
            "resource_count": 1,
            "issued": None,
            "modified": None,
            # custom columns
            "url": url,
            "format": link.get("format", "?"),
            "prefix": prefix,
            "year_signal": years[0] if years else None,
            "topic": topic,
        })

    summary = {
        "total_links_exact": len(all_data_links),
        "area_pages_scanned": len(area_pages),
        "by_format": by_format,
        "prefix_matrix": prefix_matrix,
        "series": series_serializable,
        "years_range": [min(years_set), max(years_set)] if years_set else [],
        "topics": dict(Counter(_guess_topic(link["url"], topic_hint) for link in all_data_links)),
        "method": "csv_magnet_area_pages_direct",
    }

    return summary, rows


# ─── Collector Interface ──────────────────────────────────────────────────────


def collect(source_id: str, source_cfg: dict[str, Any], captured_at: str) -> CollectorResult:
    """Collect HTML portal stats via CSV magnet quick survey.

    Strategia:
      - sitemap_url → _scan_sitemap (sample pages, estimate)
      - area_pages → _scan_area_pages (full fetch, exact count)
      - homepage only → quick probe only

    Returns:
        CollectorResult with rows (data link URLs) and summary (stats).
    """
    base_url = source_cfg.get("base_url", "")
    if not base_url:
        return CollectorResult(
            rows=[],
            summary={"error": "no base_url configured"},
        )

    html_portal_cfg = source_cfg.get("html_portal", {})
    sitemap_url = html_portal_cfg.get("sitemap_url")
    area_pages = html_portal_cfg.get("area_pages", [])
    topic_hint = html_portal_cfg.get("topic_hint")
    delay = html_portal_cfg.get("delay_seconds", 0.2)

    if sitemap_url:
        sample = html_portal_cfg.get("sample_pages", 10)
        summary, rows = _scan_sitemap(
            sitemap_url,
            topic_hint,
            source_id,
            base_url,
            sample_pages=sample,
            page_delay=delay,
        )
    elif area_pages:
        summary, rows = _scan_area_pages(
            area_pages,
            topic_hint,
            source_id,
            base_url,
            page_delay=delay,
        )
    else:
        # Homepage only probe
        response, fetch_err = observatory_ssl_fallback_get(base_url, timeout=15)
        if fetch_err or response is None:
            return CollectorResult(
                rows=[],
                summary={"type": "csv_magnet_error", "message": fetch_err},
            )
        parser = _DataLinksParser(base_url, response.text)
        rows = []
        for link in parser.links:
            url = link["url"]
            filename = url.split("/")[-1].rsplit(".", 1)[0]
            years = _extract_years(filename)
            topic = _guess_topic(url, topic_hint)
            item_id = filename[:100]
            rows.append({
                # canonical columns
                "source_id": source_id,
                "source_kind": "catalog",
                "protocol": "html",
                "source_url": base_url,
                "item_id": item_id,
                "item_name": _extract_prefix(filename),
                "item_slug": item_id,
                "title": f"{_extract_prefix(filename)} {topic}",
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "landing_page": None,
                "distribution_url": url,
                "datastore_active": False,
                "resource_count": 1,
                "issued": None,
                "modified": None,
                # custom columns
                "url": url,
                "format": link.get("format", "?"),
                "prefix": _extract_prefix(filename),
                "year_signal": years[0] if years else None,
                "topic": topic,
            })
        summary = {
            "total_links_exact": len(rows),
            "method": "csv_magnet_homepage_only",
        }

    if "error" in summary:
        return CollectorResult(
            rows=[],
            summary={"type": "csv_magnet_error", "message": summary["error"], "source_id": source_id},
        )

    summary["type"] = "csv_magnet"
    summary["source_id"] = source_id

    return CollectorResult(rows=rows, summary=summary)
