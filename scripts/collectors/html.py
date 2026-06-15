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
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from lab_connectors.http import HttpClient
from toolkit.scout.http import probe_url_headers, resolve_preview_kind

from .base import CollectorResult

DATA_EXTENSIONS = {".csv", ".json", ".xlsx", ".xls", ".ods", ".zip", ".xml", ".geojson"}

# ─── HTML Parsing ──────────────────────────────────────────────────────────────


def _extract_page_meta(html: str) -> dict[str, str]:
    """Estrae title e description da HTML."""
    meta: dict[str, str] = {}

    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        if raw.startswith("Open Data - "):
            raw = raw[12:]
        meta["title"] = raw

    desc = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if desc:
        meta["description"] = desc.group(1).strip()[:200]

    return meta


def _extract_data_links(base_url: str, html: str) -> list[dict[str, str]]:
    """Estrae link a file data da HTML già scaricato.

    Returns:
        list of {url, format, title}
    """

    class _Parser(HTMLParser):
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
            # Ordina per lunghezza decrescente: .xlsx prima di .xls, .geojson prima di .json
            for ext in sorted(DATA_EXTENSIONS, key=len, reverse=True):
                if ext in lower:
                    fmt = ext.lstrip(".").upper()
                    break
            if not fmt:
                return
            title = (attrs_dict.get("aria-label") or attrs_dict.get("title") or "").strip()
            self.links.append({"url": full_url, "format": fmt, "title": title})

    parser = _Parser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.links


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


def _guess_topic(url: str, topic_hint: str | None) -> str:
    return topic_hint or "unknown"


# ─── Sitemap Helper ───────────────────────────────────────────────────────────


def _fetch_sitemap(sitemap_url: str, timeout: int = 15) -> tuple[list[str] | None, str | None]:
    """Fetch e parse sitemap XML, ritorna lista di <loc> URL."""
    import xml.etree.ElementTree as ET

    try:
        client = HttpClient(timeout=timeout)
        result = client.get(sitemap_url)
        if not result.is_ok or result.response is None:
            err_str = str(result.err) if result.err else "unknown"
            return None, err_str
        response = result.response
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


# ─── Shared row building & stats ─────────────────────────────────────────────


def _build_row(
    link: dict[str, str],
    source_id: str,
    base_url: str,
    topic_hint: str | None,
    *,
    page_meta: dict[str, dict[str, str]] | None = None,
    data_page_url: str | None = None,
) -> dict[str, Any]:
    """Costruisce una riga per source-check da un data link."""
    url = link["url"]
    filename = url.split("/")[-1].rsplit(".", 1)[0]
    prefix = _extract_prefix(filename)
    years = _extract_years(filename)
    topic = _guess_topic(url, topic_hint)

    page_title: str | None = None
    page_desc: str | None = None
    if page_meta and data_page_url:
        meta = page_meta.get(data_page_url)
        if meta:
            page_title = meta.get("title")
            page_desc = meta.get("description")

    return {
        "source_id": source_id,
        "source_kind": "catalog",
        "protocol": "html",
        "source_url": base_url,
        "item_id": filename[:100],
        "item_name": prefix,
        "item_slug": filename[:100],
        "title": page_title or f"{prefix} {topic}",
        "organization": None,
        "tags": None,
        "notes_excerpt": page_desc,
        "landing_page": data_page_url,
        "distribution_url": url,
        "datastore_active": False,
        "resource_count": 1,
        "issued": None,
        "modified": None,
        "url": url,
        "format": link.get("format", "?"),
        "prefix": prefix,
        "year_signal": years[0] if years else None,
        "topic": topic,
    }


def _compute_summary(
    all_data_links: list[dict[str, str]],
    topic_hint: str | None,
    *,
    method: str,
    total_pages: int | None = None,
    pages_probed: int | None = None,
    pages_sampled: int | None = None,
    area_pages_scanned: int | None = None,
) -> dict[str, Any]:
    """Calcola le statistiche aggregate da una lista di data link."""
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

    series_serializable = {
        prefix: {
            "years": sorted(list(info["years"])),
            "count": info["count"],
            "sample": info["sample"],
        }
        for prefix, info in series.items()
    }

    summary: dict[str, Any] = {
        "by_format": by_format,
        "prefix_matrix": prefix_matrix,
        "series": series_serializable,
        "years_range": [min(years_set), max(years_set)] if years_set else [],
        "topics": dict(Counter(_guess_topic(link["url"], topic_hint) for link in all_data_links)),
        "method": method,
    }

    if total_pages is not None:
        summary["total_pages_in_sitemap"] = total_pages
    if pages_probed is not None and pages_sampled is not None:
        links_per_page = len(all_data_links) / pages_probed if pages_probed > 0 else 0
        summary["pages_probed"] = pages_probed
        summary["pages_sampled"] = pages_sampled
        summary["links_found_in_sample"] = len(all_data_links)
        summary["links_per_page_estimate"] = round(links_per_page, 2)
        summary["total_links_estimate"] = int(links_per_page * total_pages) if total_pages else 0
    if area_pages_scanned is not None:
        summary["area_pages_scanned"] = area_pages_scanned
        summary["total_links_exact"] = len(all_data_links)

    return summary


# ─── Core Scan ───────────────────────────────────────────────────────────────


def _scan_sitemap(
    sitemap_url: str,
    topic_hint: str | None,
    source_id: str,
    base_url: str,
    *,
    sample_pages: int = 30,
    page_delay: float = 0.2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Scan un portale HTML via sitemap con quick sample.

    1. Parse sitemap → dataset page URLs
    2. Campiona N pagine direttamente dal sitemap
    3. Fetch sample → estrae data link pattern
    4. Stima total links dal sample

    Returns:
        (rows list, scan_params dict with method / total_pages / pages_probed / pages_sampled)
        On error: ([], {"error": "reason"})
    """
    sitemap_urls, sitemap_err = _fetch_sitemap(sitemap_url)
    if sitemap_err or sitemap_urls is None:
        return [], {"error": f"sitemap failed: {sitemap_err}"}

    dataset_signals = (
        "/it/dataset/",
        "/dataset/",
        "/dati/",
        "/open-data/",
        "/opendata/",
        "/catalogo/",
    )
    dataset_page_urls = [u for u in sitemap_urls if any(s in u.lower() for s in dataset_signals)]

    if not dataset_page_urls:
        return [], {"error": "no dataset pages found in sitemap"}

    total_pages = len(dataset_page_urls)

    # Sample N pages directly from sitemap
    sampled = list(dataset_page_urls[:])  # copy
    random.shuffle(sampled)
    sample_size = min(sample_pages, len(sampled))
    sampled = sampled[:sample_size]

    all_data_links: list[dict[str, str]] = []
    seen_dedup_keys: set[tuple[str, str]] = set()
    pages_probed = 0
    page_meta: dict[str, dict[str, str]] = {}  # page_url → {title, description}

    for page_url in sampled:
        time.sleep(page_delay)
        # Fetch page directly — no separate HEAD probe (saves one round-trip)
        client = HttpClient(timeout=10)
        result = client.get(page_url)
        if not result.is_ok or result.response is None:
            continue
        pages_probed += 1

        # Extract page metadata (title, description) for enrichment
        page_meta[page_url] = _extract_page_meta(result.response.text)

        links = _extract_data_links(page_url, result.response.text)
        for link in links:
            dk = (link["url"], link.get("format") or "")
            if dk not in seen_dedup_keys:
                seen_dedup_keys.add(dk)
                link["_page_url"] = page_url  # track provenance for metadata enrichment
                all_data_links.append(link)

    rows = [
        _build_row(
            link,
            source_id,
            base_url,
            topic_hint,
            page_meta=page_meta,
            data_page_url=link.get("_page_url"),
        )
        for link in all_data_links
    ]

    scan_params: dict[str, Any] = {
        "method": "csv_magnet_sitemap_sample",
        "total_pages": total_pages,
        "pages_probed": pages_probed,
        "pages_sampled": sample_size,
    }

    return rows, scan_params


def _scan_area_pages(
    area_pages: list[str],
    topic_hint: str | None,
    source_id: str,
    base_url: str,
    *,
    page_delay: float = 0.2,
    page_url_template: str | None = None,
    page_start: int = 0,
    page_max: int = 200,
    page_stop_on_empty: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Scan portale HTML via area_pages (nessun second-level crawl).

    Fetch ogni area page direttamente → estrae tutti i link data.
    Tutto il contenido è sulla pagina area, no pagine figlie.

    Se page_url_template è impostato (es. "https://site.it/page={page}"),
    enumera le pagine automaticamente partendo da page_start, fermandosi
    quando trova una pagina vuota (nessun link data) o raggiunge page_max.

    Error handling: nel branch paginato si usa break su errore (perché le
    pagine sono URL sequenziali sullo stesso server — se una cade, cadono
    tutte). Nel branch area_pages legacy si usa continue (ogni URL è
    indipendente, un errore non implica gli altri).

    Returns:
        (rows list, scan_params dict with method / area_pages_scanned)
    """
    all_data_links: list[dict[str, str]] = []
    seen_dedup_keys: set[tuple[str, str]] = set()
    pages_scanned = 0
    page_meta: dict[str, dict[str, str]] = {}

    if page_url_template:
        page = page_start
        # SSL probe: se la prima pagina va in fallback SSL, usa verify=False
        # per tutte le successive (evita overhead SSL per ogni pagina).
        _ssl_bypass = False
        while pages_scanned < page_max:
            area_url = page_url_template.format(page=page)
            time.sleep(page_delay)
            client = HttpClient(timeout=5)
            if _ssl_bypass:
                result = client.get(area_url, verify=False)
            else:
                result = client.get(area_url)
                if result.ssl_fallback_used:
                    _ssl_bypass = True
            if not result.is_ok or result.response is None:
                break
            page_meta[area_url] = _extract_page_meta(result.response.text)
            links = _extract_data_links(area_url, result.response.text)
            links_this_page = []
            for link in links:
                dk = (link["url"], link.get("format") or "")
                if dk not in seen_dedup_keys:
                    seen_dedup_keys.add(dk)
                    links_this_page.append(link)
                    all_data_links.append(link)
            if not links and page_stop_on_empty:
                pages_scanned += 1
                break
            pages_scanned += 1
            page += 1
        area_pages_scanned = pages_scanned
    else:
        for area_url in area_pages:
            time.sleep(page_delay)
            client = HttpClient(timeout=15)
            result = client.get(area_url)
            if not result.is_ok or result.response is None:
                continue
            page_meta[area_url] = _extract_page_meta(result.response.text)
            links = _extract_data_links(area_url, result.response.text)
            for link in links:
                dk = (link["url"], link.get("format") or "")
                if dk not in seen_dedup_keys:
                    seen_dedup_keys.add(dk)
                    link["_page_url"] = area_url
                    all_data_links.append(link)
        area_pages_scanned = len(area_pages)

    rows = [
        _build_row(
            link,
            source_id,
            base_url,
            topic_hint,
            page_meta=page_meta,
            data_page_url=link.get("_page_url") or None,
        )
        for link in all_data_links
    ]

    method = (
        "csv_magnet_area_pages_paginated" if page_url_template else "csv_magnet_area_pages_direct"
    )
    scan_params: dict[str, Any] = {
        "method": method,
        "area_pages_scanned": area_pages_scanned,
    }

    return rows, scan_params


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
    html_portal_cfg = source_cfg.get("html_portal", {})

    # base_url da config, con fallback a html_portal.homepage
    # (entrambi i campi sono usati nel registry, homepage è più specifico)
    base_url = source_cfg.get("base_url") or html_portal_cfg.get("homepage") or ""
    if not base_url:
        return CollectorResult(
            rows=[],
            summary={"error": "no base_url configured"},
        )
    sitemap_url = html_portal_cfg.get("sitemap_url")
    area_pages = html_portal_cfg.get("area_pages", [])
    topic_hint = html_portal_cfg.get("topic_hint")
    delay = html_portal_cfg.get("delay_seconds", 0.2)
    page_url_template = html_portal_cfg.get("page_url_template")
    page_start = html_portal_cfg.get("page_start", 0)
    page_max = html_portal_cfg.get("page_max", 200)
    page_stop_on_empty = html_portal_cfg.get("page_stop_on_empty", True)
    probe_ct = html_portal_cfg.get("probe_content_type", False)

    rows: list[dict[str, Any]] = []
    scan_params: dict[str, Any] = {}

    if sitemap_url:
        sample = html_portal_cfg.get("sample_pages", 30)
        rows, scan_params = _scan_sitemap(
            sitemap_url,
            topic_hint,
            source_id,
            base_url,
            sample_pages=sample,
            page_delay=delay,
        )
    elif area_pages or page_url_template:
        rows, scan_params = _scan_area_pages(
            area_pages,
            topic_hint,
            source_id,
            base_url,
            page_delay=delay,
            page_url_template=page_url_template,
            page_start=page_start,
            page_max=page_max,
            page_stop_on_empty=page_stop_on_empty,
        )
    else:
        # Homepage only probe
        client = HttpClient(timeout=5)
        result = client.get(base_url)
        if not result.is_ok or result.response is None:
            err_msg = str(result.err) if result.err else "unknown"
            return CollectorResult(
                rows=[],
                summary={"type": "csv_magnet_error", "message": err_msg},
            )
        page_meta = {base_url: _extract_page_meta(result.response.text)}
        links = _extract_data_links(base_url, result.response.text)
        rows = [
            _build_row(
                link, source_id, base_url, topic_hint, page_meta=page_meta, data_page_url=base_url
            )
            for link in links
        ]
        scan_params = {"method": "csv_magnet_homepage_only"}

    # Check for scan error
    if "error" in scan_params:
        return CollectorResult(
            rows=[],
            summary={
                "type": "csv_magnet_error",
                "message": scan_params["error"],
                "source_id": source_id,
            },
        )

    # Content-Type probe (opt-in): arricchisce formato per URL ambigui
    # ESEGUITO PRIMA di _compute_summary — così by_format è già corretto
    if probe_ct:
        _probe_targets = [
            r for r in rows if r.get("url") and r.get("format") in ("?", "ZIP", "BIN")
        ]
        for row in _probe_targets[:20]:  # max 20 probe per run
            try:
                _info = probe_url_headers(row["url"], timeout=5)
                ct_fmt = resolve_preview_kind(
                    row["url"],
                    content_type=_info.get("content_type"),
                    content_disposition=_info.get("content_disposition"),
                )
            except Exception:
                ct_fmt = None
            if ct_fmt:
                row["format"] = ct_fmt

    # Compute summary from rows (formats are already probed)
    all_data_links = [{"url": r["distribution_url"], "format": r.get("format", "?")} for r in rows]
    summary = _compute_summary(all_data_links, topic_hint, **scan_params)

    summary["type"] = "csv_magnet"
    summary["source_id"] = source_id

    if probe_ct:
        summary["content_type_probes"] = min(
            len([r for r in rows if r.get("format") not in ("?",)]), 20
        )

    return CollectorResult(rows=rows, summary=summary)
