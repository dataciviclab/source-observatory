"""HTML portal collector — CSV Magnet scan for portals without structured API.

Phase 2 della pipeline SO: quick survey per portali HTML senza API catalog.

Strategia:
  - Se sitemap_url: parse sitemap → campione N pagine → infer pattern → estimate
  - Se area_pages: fetch diretto di ogni area page → link data diretti

Output:
  - rows: [{url, format, prefix, year_signal, topic, landing_page}] — per source-check
  - summary: {total_links_estimate, by_format, prefix_matrix, series, topics, method}

Non fa full crawl (191 pagine). Campiona per stimare.

Il motore di estrazione link e raggruppamento è in ``toolkit.scout.link_extractor``.
Questo modulo è solo orchestratore: fetch pagine, costruisce righe SO, calcola summary.

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

from lab_connectors.http import HttpClient
from toolkit.scout.http import probe_url_headers, resolve_preview_kind
from toolkit.scout.link_extractor import DataLink, extract_data_links, group_links

from .base import CollectorResult

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


# ─── URL Analysis (mantenuto per backward compat nei test SO) ─────────────────


def _extract_prefix(filename: str) -> str:
    """Delega a toolkit.scout.link_extractor."""
    from toolkit.scout.link_extractor import _extract_prefix as _tk_prefix

    return _tk_prefix(filename)


def _extract_years(filename: str) -> list[int]:
    """Delega a toolkit.scout.link_extractor."""
    from toolkit.scout.link_extractor import _extract_years as _tk_years

    return _tk_years(filename)


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
    link: DataLink,
    source_id: str,
    base_url: str,
    topic_hint: str | None,
    *,
    page_meta: dict[str, dict[str, str]] | None = None,
    data_page_url: str | None = None,
) -> dict[str, Any]:
    """Costruisce una riga per source-check da un DataLink."""
    url = link.url
    prefix = link.prefix
    years = link.years
    topic = _guess_topic(url, topic_hint)
    filename = url.split("/")[-1].rsplit(".", 1)[0]

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
        "landing_page": data_page_url or link.page_url or base_url,
        "distribution_url": url,
        "datastore_active": False,
        "resource_count": 1,
        "issued": None,
        "modified": None,
        "url": url,
        "format": link.format,
        "prefix": prefix,
        "year_signal": years[0] if years else None,
        "topic": topic,
    }


def _compute_summary(
    all_data_links: list[DataLink],
    rows: list[dict[str, Any]],
    topic_hint: str | None,
    *,
    method: str,
    total_pages: int | None = None,
    pages_probed: int | None = None,
    pages_sampled: int | None = None,
    area_pages_scanned: int | None = None,
) -> dict[str, Any]:
    """Calcola le statistiche aggregate da una lista di DataLink.

    Usa ``group_links`` dal toolkit per raggruppamento intelligente.
    """
    # Statistiche base
    by_format: dict[str, int] = {}
    years_set: set[int] = set()
    for link in all_data_links:
        fmt = link.format
        by_format[fmt] = by_format.get(fmt, 0) + 1
        for y in link.years:
            years_set.add(y)

    # Raggruppamento intelligente via toolkit
    groups = group_links(all_data_links)

    prefix_matrix: dict[str, int] = {}
    for g in groups:
        prefix_matrix[g.prefix or g.group_id] = g.count

    series_serializable = {
        g.prefix or g.group_id: {
            "years": g.year_range,
            "count": g.count,
            "formats": sorted(g.formats),
            "sample": g.links[0].url.split("/")[-1] if g.links else "",
        }
        for g in groups
    }

    summary: dict[str, Any] = {
        "by_format": by_format,
        "prefix_matrix": prefix_matrix,
        "series": series_serializable,
        "groups": [
            {
                "group_id": g.group_id,
                "prefix": g.prefix,
                "count": g.count,
                "year_range": g.year_range,
                "formats": sorted(g.formats),
            }
            for g in groups
        ],
        "years_range": [min(years_set), max(years_set)] if years_set else [],
        "topics": dict(Counter(_guess_topic(link.url, topic_hint) for link in all_data_links)),
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

    all_data_links: list[DataLink] = []
    seen_urls: set[str] = set()
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

        links = extract_data_links(page_url, result.response.text)
        for link in links:
            if link.url not in seen_urls:
                seen_urls.add(link.url)
                link.page_url = page_url  # track provenance for metadata enrichment
                all_data_links.append(link)

    rows = [
        _build_row(
            link,
            source_id,
            base_url,
            topic_hint,
            page_meta=page_meta,
            data_page_url=link.page_url or None,
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
    all_data_links: list[DataLink] = []
    seen_urls: set[str] = set()
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
            links = extract_data_links(area_url, result.response.text)
            links_this_page = []
            for link in links:
                if link.url not in seen_urls:
                    seen_urls.add(link.url)
                    link.page_url = area_url
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
            links = extract_data_links(area_url, result.response.text)
            for link in links:
                if link.url not in seen_urls:
                    seen_urls.add(link.url)
                    link.page_url = area_url
                    all_data_links.append(link)
        area_pages_scanned = len(area_pages)

    rows = [
        _build_row(
            link,
            source_id,
            base_url,
            topic_hint,
            page_meta=page_meta,
            data_page_url=link.page_url or None,
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
        links = extract_data_links(base_url, result.response.text)
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

    # Compute summary (groups e statistiche)
    # Ricostruisce DataLink da rows per group_links dopo eventuali probe CT
    _summary_links = [
        DataLink(
            url=r["distribution_url"],
            format=r.get("format", "?"),
            prefix=r.get("prefix", ""),
            years=[r["year_signal"]] if r.get("year_signal") else [],
        )
        for r in rows
    ]
    summary = _compute_summary(_summary_links, rows, topic_hint, **scan_params)

    summary["type"] = "csv_magnet"
    summary["source_id"] = source_id

    # Homepage branch: _compute_summary senza area_pages_scanned non produce total_links_exact
    if scan_params.get("method") == "csv_magnet_homepage_only":
        summary["total_links_exact"] = len(rows)

    if probe_ct:
        summary["content_type_probes"] = min(
            len([r for r in rows if r.get("format") not in ("?",)]), 20
        )

    return CollectorResult(rows=rows, summary=summary)
