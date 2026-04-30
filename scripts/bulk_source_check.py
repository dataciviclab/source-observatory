#!/usr/bin/env python3
"""
Bulk source-check su una selezione del catalogo.

Per ogni item del catalogo:
  - CKAN (inps, openbdap, ...): chiama package_show per recuperare title,
    notes, tags, risorse (url + format), copertura temporale dagli extras.
  - SDMX (istat_sdmx): chiama /dataflow per leggere le annotations
    LAYOUT_DATAFLOW_KEYWORDS (granularità + anni già strutturati).
  - Fallback: inferisce granularità e anni da titolo + tag con regex.
  Fa poi HEAD HTTP sull'URL più rilevante trovato.

Output: source_check_results.parquet

Uso:
    python scripts/bulk_source_check.py
    python scripts/bulk_source_check.py --source-ids inps istat_sdmx
    python scripts/bulk_source_check.py --source-ids openbdap --limit 50 --include-no-url
    python scripts/bulk_source_check.py --out data/mycheck.parquet
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collectors.base import observatory_get, observatory_head, get_pooled_session

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_latest.parquet"
DEFAULT_OUT = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "source_check_results.parquet"
REGISTRY_PATH = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"

HTTP_TIMEOUT = 15
MAX_WORKERS = 8

SDMX_NS = {
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "structure": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "generic": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
}


# ── registry ─────────────────────────────────────────────────────────────────

def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ── euristica granularità ─────────────────────────────────────────────────────

_GRAN_PATTERNS: list[tuple[str, str]] = [
    (r"\bcomun[ei]\b|\bmunicip", "comune"),
    (r"\bprovinc", "provincia"),
    (
        r"\bregion[ei]\b|\bregioni\b|piemonte|lombardia|veneto|emilia|toscana|lazio|campania|puglia|sicilia|sardegna|abruzzo|umbria|marche|molise|calabria|basilicata|friuli|trentin|liguria|valle d['\s]aosta",
        "regione",
    ),
    (r"\bnazional[ei]\b|\bitali[ae]\b|\bnazione\b|\bnational\b|\bregional\b", "nazionale"),
    (r"\beurope[ao]\b|\bue\b|\beuropa\b|\beuropean\b", "europeo"),
]

def _infer_granularity(text: str) -> str:
    low = text.lower()
    for pattern, label in _GRAN_PATTERNS:
        if re.search(pattern, low):
            return label
    return "non_determinato"


# ── euristica anni ────────────────────────────────────────────────────────────

# Anni isolati classici: boundary non-digit su entrambi i lati
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20[012]\d)(?!\d)")
# Anni in blocchi compatti: boundary non-digit solo a sinistra (202122 → cattura 2021)
_YEAR_START_RE = re.compile(r"(?:^|(?<!\d))(20[012]\d)")
# Per year pair: 4 cifre 20XX seguite da 2 cifre YY che sembrano anno (202122 → 2021+2022)
# Prova a scomporre quando le due cifre finale < 30 (anno 20YY)
_COMPACT_YEAR_PAIR_RE = re.compile(r"(20[012]\d)(\d{2})(?=20|$|\D)")


def _infer_years(text: str) -> tuple[Optional[int], Optional[int]]:
    years: set[int] = set()

    # Anni isolati classici: boundary non-digit su entrambi i lati
    for y in _YEAR_RE.findall(text):
        years.add(int(y))

    # Anni in blocchi compatti: in "202122" cattura 2021 anche se seguito da cifre
    # (ma solo 2000-2029 per evitare 2030+)
    for y in _YEAR_START_RE.findall(text):
        years.add(int(y))

    # Prova a scomporre pattern compatto AABBCC = 20XX + YY: 202122 → 2021 + 2022
    # 2 cifre finali < 30 → probabile anno 20YY
    for first_str, second_str in _COMPACT_YEAR_PAIR_RE.findall(text):
        y1 = int(first_str)
        y2_2digit = int(second_str)
        if y2_2digit <= 30:  # anno 20YY
            y2 = 2000 + y2_2digit
            if y2 > y1 and y2 - y1 <= 10:  # solo coppie adiacenti (2021+2022, 2025+2026)
                years.add(y1)
                years.add(y2)

    if not years:
        return None, None
    return min(years), max(years)


# ── HTTP check ────────────────────────────────────────────────────────────────

def _http_head(url: str, session: Optional[requests.Session] = None) -> tuple[Optional[int], bool, str]:
    if not isinstance(url, str) or not url.startswith("http"):
        return None, False, "url_missing_or_invalid"
    try:
        if session is not None:
            resp = session.head(url, timeout=HTTP_TIMEOUT)
        else:
            resp = observatory_head(url, timeout=HTTP_TIMEOUT)
        reachable = resp.status_code < 400
        return resp.status_code, reachable, ""
    except requests.exceptions.SSLError:
        return None, False, "ssl_error"
    except requests.exceptions.ConnectionError:
        return None, False, "connection_error"
    except requests.exceptions.Timeout:
        return None, False, "timeout"
    except Exception as exc:
        return None, False, str(exc)[:120]


# ── CKAN enrichment ───────────────────────────────────────────────────────────

def _fetch_ckan_package(base_api: str, item_name: str, session: Optional[requests.Session] = None) -> Optional[dict]:
    url = f"{base_api}/package_show?id={item_name}"
    try:
        if session is not None:
            with session.get(url, timeout=HTTP_TIMEOUT) as r:
                if r.status_code != 200:
                    return None
                data = r.json()
        else:
            r = observatory_get(url, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                return None
            data = r.json()
        if not data.get("success"):
            return None
        return data.get("result") or None
    except Exception:
        return None


def _parse_ckan_package(pkg: dict) -> dict:
    """Estrae i campi utili da un package CKAN."""
    tags = [
        (t.get("display_name") or t.get("name") or "")
        for t in (pkg.get("tags") or [])
        if isinstance(t, dict)
    ]

    # estrai groups per arricchire l'inferenza di granularità
    groups = [
        (g.get("display_name") or g.get("name") or "")
        for g in (pkg.get("groups") or [])
        if isinstance(g, dict)
    ]

    resources = pkg.get("resources") or []
    resource_url = None
    resource_format = None
    for res in resources:
        u = res.get("url") or ""
        if u.startswith("http"):
            resource_url = u
            resource_format = res.get("format") or None
            break

    # copertura temporale dagli extras (DCAT-AP)
    extras = {e["key"]: e["value"] for e in (pkg.get("extras") or []) if isinstance(e, dict)}
    temporal_start = extras.get("temporal_coverage_from") or extras.get("issued")
    temporal_end = extras.get("temporal_coverage_to") or extras.get("modified")

    # fallback DCAT-IT: "Periodo di riferimento: YYYY - YYYY"
    # presente in molti CKAN italiani (MEF/Consip, Regioni, etc.)
    if temporal_start is None and temporal_end is None:
        periodo = extras.get("Periodo di riferimento") or extras.get("periodo di riferimento")
        if periodo:
            years = _YEAR_RE.findall(str(periodo))
            if len(years) >= 2:
                temporal_start, temporal_end = years[0], years[-1]

    notes = (pkg.get("notes") or "").strip()
    title = pkg.get("title") or None

    # groups hanno precedenza: concatena prima di notes per influenzare l'inferenza
    combined = " ".join(filter(None, [title, ", ".join(groups), ", ".join(tags), notes[:500]]))
    granularity = _infer_granularity(combined)

    # anni: prima dagli extras, poi dal testo
    year_min, year_max = None, None
    if temporal_start:
        ys, _ = _infer_years(temporal_start)
        year_min = ys
    if temporal_end:
        _, ye = _infer_years(temporal_end)
        year_max = ye
    if year_min is None or year_max is None:
        yt_min, yt_max = _infer_years(combined)
        year_min = year_min or yt_min
        year_max = year_max or yt_max

    return {
        "enriched_title": title,
        "enriched_tags": ", ".join(tags) if tags else None,
        "enriched_notes": notes[:300] if notes else None,
        "resource_url": resource_url,
        "resource_format": resource_format,
        "granularity": granularity,
        "year_min": year_min,
        "year_max": year_max,
        "enrich_method": "ckan_package_show",
    }


# ── SDMX enrichment ───────────────────────────────────────────────────────────

def _fetch_sdmx_years(base_url: str, flow_id: str, session: Optional[requests.Session] = None) -> tuple[Optional[int], Optional[int]]:
    """Chiama l'endpoint dati SDMX per ricavare year_min/year_max dalla dimensione TIME_PERIOD."""
    try:
        # ricava la root SDMX togliendo /dataflow/IT1 (o simile) dal base_url
        base = base_url.split("?")[0].rstrip("/")
        # risali fino alla root del servizio REST (prima di /dataflow)
        if "/dataflow/" in base:
            sdmx_root = base[: base.index("/dataflow/")]
        elif base.endswith("/dataflow"):
            sdmx_root = base[: -len("/dataflow")]
        else:
            sdmx_root = base
        url = f"{sdmx_root}/data/{flow_id}?lastNObservations=1"
        if session is not None:
            with session.get(url, timeout=20) as r:
                if r.status_code != 200:
                    return None, None
                content = r.content
        else:
            r = observatory_get(url, timeout=20)
            if r.status_code != 200:
                return None, None
            content = r.content
        root = ET.fromstring(content)
        time_values: list[str] = []
        # pattern 1: <generic:Value id="TIME_PERIOD" value="..."/> dentro <generic:ObsKey>
        for val_el in root.findall(".//generic:ObsKey/generic:Value", SDMX_NS):
            if val_el.get("id") == "TIME_PERIOD":
                v = val_el.get("value")
                if v:
                    time_values.append(v)
        # pattern 2: attributo TIME_PERIOD su <generic:Obs> o <generic:ObsValue>
        for obs_el in root.findall(".//generic:Obs", SDMX_NS):
            v = obs_el.get("TIME_PERIOD")
            if v:
                time_values.append(v)
        for obs_el in root.findall(".//generic:ObsValue", SDMX_NS):
            v = obs_el.get("TIME_PERIOD")
            if v:
                time_values.append(v)
        years: list[int] = []
        for tv in time_values:
            found = _YEAR_RE.findall(tv)
            years.extend(int(y) for y in found)
        if not years:
            return None, None
        return min(years), max(years)
    except Exception:
        return None, None


def _fetch_sdmx_dataflow(base_url: str, flow_id: str, session: Optional[requests.Session] = None) -> Optional[ET.Element]:
    # rimuovi query string e normalizza
    base = base_url.split("?")[0].rstrip("/")
    # risali alla root se l'url punta al listing completo
    if base.endswith("/IT1"):
        root_url = base
    else:
        root_url = base.rsplit("/", 1)[0]
    url = f"{root_url}/{flow_id}"
    try:
        if session is not None:
            with session.get(url, timeout=HTTP_TIMEOUT) as r:
                if r.status_code != 200:
                    return None
                content = r.content
        else:
            r = observatory_get(url, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                return None
            content = r.content
        return ET.fromstring(content)
    except Exception:
        return None


def _parse_sdmx_annotations(xml_root: ET.Element, base_url: str, flow_id: str) -> dict:
    annotations: dict[str, str] = {}
    for ann in xml_root.findall(".//common:Annotation", SDMX_NS):
        atype_el = ann.find("common:AnnotationType", SDMX_NS)
        atext_el = ann.find("common:AnnotationText", SDMX_NS)
        if atype_el is not None and atext_el is not None:
            annotations[atype_el.text or ""] = atext_el.text or ""

    keywords_raw = annotations.get("LAYOUT_DATAFLOW_KEYWORDS", "")
    # formato: "keyword1+keyword2+...+keyword3+..."
    keywords = [k.strip().lower() for part in keywords_raw.split("+") for k in part.split(",") if k.strip()]

    combined = " ".join(keywords)
    granularity = _infer_granularity(combined)
    year_min, year_max = _infer_years(combined)

    # se le annotations non contengono anni, prova a ricavarli dall'endpoint dati
    if year_min is None:
        year_min, year_max = _fetch_sdmx_years(base_url, flow_id)

    metadata_url = annotations.get("METADATA_URL")

    return {
        "enriched_title": None,
        "enriched_tags": ", ".join(keywords[:10]) if keywords else None,
        "enriched_notes": keywords_raw[:300] if keywords_raw else None,
        "resource_url": metadata_url,
        "resource_format": "SDMX",
        "granularity": granularity,
        "year_min": year_min,
        "year_max": year_max,
        "enrich_method": "sdmx_dataflow_annotations",
    }


# ── HTML enrichment (fallback per landing_page) ───────────────────────────────

def _fetch_html_metadata(url: str, session: Optional[requests.Session] = None) -> dict:
    """Estrae metadati leggeri da una landing_page HTML.

    Ricerca:
      - Link a file scaricabili (.csv, .json, .xlsx, .xls, .xml, .zip, .pdf)
      - Meta tag DCAT (dcterms.temporal, dcterms.spatial)

    Restituisce dict con resource_format (primo formato trovato o None),
    enriched_notes (None), enrich_method.
    """
    if not isinstance(url, str) or not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "html_scrape_failed"
        return result

    try:
        if session is not None:
            with session.get(url, timeout=10, stream=False) as resp:
                resp.raise_for_status()
                # resp.text uses requests encoding detection (Content-Type charset),
                # which may differ from the UTF-8 fallback used when session is None.
                # Divergence is acceptable for regex-based link extraction.
                html = resp.text
        else:
            resp = observatory_get(url, timeout=10, stream=False)
            resp.raise_for_status()
            html = resp.text

        # Limita a 200KB (usa len(stringa) come proxy ragionevole per UTF-8)
        if len(html) > 200000:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "html_scrape_failed"
            return result

        # Cerca link a file scaricabili: regex su href
        file_patterns = [r'href=["\']([^"\']*\.csv)["\']',
                        r'href=["\']([^"\']*\.json)["\']',
                        r'href=["\']([^"\']*\.xlsx)["\']',
                        r'href=["\']([^"\']*\.xls)["\']',
                        r'href=["\']([^"\']*\.xml)["\']',
                        r'href=["\']([^"\']*\.zip)["\']',
                        r'href=["\']([^"\']*\.pdf)["\']']

        resource_format = None
        for pattern in file_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                # Prendi il primo formato trovato
                filename = matches[0]
                ext = filename.rsplit(".", 1)[-1].upper() if "." in filename else None
                if ext:
                    resource_format = ext
                    break

        return {
            "enriched_title": None,
            "enriched_tags": None,
            "enriched_notes": None,
            "resource_url": None,
            "resource_format": resource_format,
            "granularity": None,
            "year_min": None,
            "year_max": None,
            "enrich_method": "html_scrape",
        }
    except Exception:
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "html_scrape_failed"
        return result


# ── CSV/JSON/XLS content preview ───────────────────────────────────────────────

YEAR_COLUMNS = ["anno", "year", "data", "date", "periodo", "period", "mese", "month"]
REGION_COLUMNS = ["regione", "region", "provincia", "province", "area", "territorio"]
COMUNE_COLUMNS = ["comune", "municip", "localita", "citta", "city"]


def _fetch_data_preview(url: str, session: Optional[requests.Session] = None) -> dict:
    """Fetch e parse content preview da un URL CSV/JSON/XLS.

    Estrae: column names, year_min/year_max (da colonna anno),
    granularity (da column names + sample data).

    Returns dict in formato _EMPTY_ENRICH con campi aggiuntivi:
    - columns: list[str]
    - year_min, year_max
    - granularity
    - enrich_method: "csv_preview"
    """
    if not isinstance(url, str) or not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_failed"
        return result

    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if fmt not in ("csv", "json", "xlsx", "xls"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_skipped"
        return result

    def _do_get() -> requests.Response:
        if session is not None:
            return session.get(url, timeout=HTTP_TIMEOUT)
        return observatory_get(url, timeout=HTTP_TIMEOUT)

    try:
        # Fetch ~5 KB (enough for headers + a few rows)
        # Retry once on timeout (transient network issues)
        resp = None
        for attempt in range(2):
            try:
                resp = _do_get()
                break
            except requests.exceptions.Timeout:
                if attempt == 0:
                    continue  # retry once
                else:
                    result = _EMPTY_ENRICH.copy()
                    result["enrich_method"] = "csv_preview_timeout"
                    return result
            except requests.exceptions.ConnectionError:
                if attempt == 0:
                    continue  # retry once
                else:
                    result = _EMPTY_ENRICH.copy()
                    result["enrich_method"] = "csv_preview_connection_error"
                    return result
        if resp is None:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "csv_preview_failed"
            return result
        if resp.status_code >= 400:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "csv_preview_http_error"
            return result

        content = resp.content
        if len(content) > 100 * 1024:
            content = content[:100 * 1024]
        text = content.decode("utf-8", errors="replace")

        columns: list[str] = []
        year_min: Optional[int] = None
        year_max: Optional[int] = None
        granularity = "non_determinato"
        year_values: list[int] = []  # defined outside if/elif so JSON branch can use it

        if fmt == "csv":
            try:
                lines = text.splitlines()[:10]
                if not lines:
                    raise ValueError("Empty CSV")
                sample_text = "\n".join(lines)
                reader = csv.reader(io.StringIO(sample_text))
                rows = list(reader)
                if not rows:
                    raise ValueError("No rows parsed")
                headers = [h.strip() for h in rows[0]]
                columns = [h for h in headers if h]

                # Find year column
                year_col_idx = None
                for i, h in enumerate(columns):
                    h_lower = h.lower()
                    if any(y in h_lower for y in YEAR_COLUMNS):
                        year_col_idx = i
                        break

                for row in rows[1:6]:
                    if year_col_idx is not None and year_col_idx < len(row):
                        found = _YEAR_RE.findall(row[year_col_idx])
                        year_values.extend(int(y) for y in found)
                    # Also scan all cells
                    for cell in row:
                        found = _YEAR_RE.findall(cell)
                        year_values.extend(int(y) for y in found)

                if year_values:
                    year_min = min(year_values)
                    year_max = max(year_values)
            except Exception:
                # CSV parse failed — try raw text scan
                found = _YEAR_RE.findall(text[:5000])
                years = [int(y) for y in found]
                if years:
                    year_min, year_max = min(years), max(years)

        elif fmt == "json":
            try:
                import json
                data = json.loads(text)
                if isinstance(data, list):
                    rows_sample = data[:5]
                    if rows_sample and isinstance(rows_sample[0], dict):
                        columns = [str(k) for k in rows_sample[0].keys()]
                        for row in rows_sample:
                            for v in row.values() if isinstance(row, dict) else []:
                                found = _YEAR_RE.findall(str(v))
                                year_values.extend(int(y) for y in found)
                elif isinstance(data, dict):
                    columns = [str(k) for k in data.keys()]
            except Exception:
                found = _YEAR_RE.findall(text[:5000])
                years = [int(y) for y in found]
                if years:
                    year_min, year_max = min(years), max(years)

        # Infer granularity from column names
        columns_lower = [c.lower() for c in columns]
        if any(c in " ".join(columns_lower) for c in COMUNE_COLUMNS):
            granularity = "comune"
        elif any(c in " ".join(columns_lower) for c in REGION_COLUMNS):
            granularity = "regione"
        elif year_min is not None and year_max is not None:
            # If we have temporal but no geographic granularity, non_determinato
            granularity = "non_determinato"

        return {
            "enriched_title": None,
            "enriched_tags": None,
            "enriched_notes": None,
            "resource_url": url,
            "resource_format": fmt.upper(),
            "granularity": granularity,
            "year_min": year_min,
            "year_max": year_max,
            "enrich_method": "csv_preview",
        }
    except Exception:
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_failed"
        return result


# ── dispatcher per protocollo ─────────────────────────────────────────────────

_EMPTY_ENRICH = {
    "enriched_title": None,
    "enriched_tags": None,
    "enriched_notes": None,
    "resource_url": None,
    "resource_format": None,
    "granularity": None,
    "year_min": None,
    "year_max": None,
    "enrich_method": "none",
}


def _enrich(row: pd.Series, registry: dict[str, Any], session: Optional[requests.Session] = None) -> dict:
    source_id = row.get("source_id") or ""
    source_cfg = registry.get(source_id, {})
    protocol = source_cfg.get("protocol") or row.get("protocol") or ""
    base_url = source_cfg.get("base_url") or row.get("source_url") or ""
    _raw_name = row.get("item_name") or row.get("item_id")
    item_name = "" if pd.isna(_raw_name) else str(_raw_name)
    # preferisci item_slug (nome testuale CKAN) per package_show
    _slug = row.get("item_slug")
    if isinstance(_slug, str) and _slug.strip():
        item_name = _slug.strip()

    has_valid_slug = False  # default; set True inside CKAN block if slug is usable
    if protocol == "ckan" and base_url and item_name:
        # _slug già letto sopra (linea 395) — non riletto
        has_valid_slug = bool(isinstance(_slug, str) and _slug.strip() and _slug.strip() != "dataset")
        if has_valid_slug:
            # usa api_base_url pre-calcolata dal layer 1 (gestisce endpoint non-standard come INPS /odapi/)
            api_base_url = row.get("api_base_url")
            base_api = api_base_url if isinstance(api_base_url, str) and api_base_url.startswith("http") else base_url
            pkg = _fetch_ckan_package(base_api, item_name, session=session)
            if pkg:
                return _parse_ckan_package(pkg)
        # CKAN senza slug valido → skip package_show, passa a HTML fallback sotto

    if protocol == "sdmx" and base_url and item_name:
        sdmx_base = base_url
        # usa api_base_url pre-calcolata se disponibile
        api_base_url = row.get("api_base_url")
        if isinstance(api_base_url, str) and api_base_url.startswith("http"):
            sdmx_base = api_base_url
        xml_root = _fetch_sdmx_dataflow(sdmx_base, item_name, session=session)
        if xml_root is not None:
            return _parse_sdmx_annotations(xml_root, sdmx_base, item_name)

    # HTML protocol: direct data URL (CSV/JSON/XLS) — fetch content preview
    if protocol == "html":
        data_url = row.get("url")
        if isinstance(data_url, str):
            parsed = urllib.parse.urlparse(data_url)
            path = parsed.path or ""
            fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if fmt in ("csv", "json", "xlsx", "xls"):
                return _fetch_data_preview(data_url, session=session)

    # HTML fallback: per tutti i source con landing_page raggiungibile
    # dati_camera ha scraping_blocked=true → salta HTML se CKAN package_show già provato
    # CKAN senza slug valido = package_show già saltato → proviamo comunque l'HTML
    landing = row.get("landing_page")
    if isinstance(landing, str) and landing.startswith("http"):
        # skip scraping_blocked sources only if CKAN package_show already attempted
        ckan_skipped_package_show = protocol == "ckan" and not has_valid_slug
        if source_cfg.get("scraping_blocked") and not ckan_skipped_package_show:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "scraping_blocked"
            return result
        return _fetch_html_metadata(landing, session=session)

    return _EMPTY_ENRICH.copy()


# ── fallback euristica su campi catalogo ──────────────────────────────────────

def _fallback_infer(row: pd.Series) -> tuple[str, Optional[int], Optional[int]]:
    combined = " ".join(
        str(v) for v in [row.get("title"), row.get("tags"), row.get("notes_excerpt")]
        if v and str(v) != "nan"
    )
    return _infer_granularity(combined), *_infer_years(combined)


# ── intake scoring ────────────────────────────────────────────────────────────

_GRAN_SCORE = {"comune": 40, "provincia": 30, "regione": 20, "nazionale": 10, "europeo": 5, "non_determinato": 0}
_FORMAT_SCORE = {"CSV": 20, "JSON": 20, "XLSX": 12, "XLS": 10, "XML": 8, "SDMX": 8, "PDF": 2}
_YEAR_SPAN_MAX = 20  # anni di copertura oltre i quali il bonus è al massimo


def _intake_score(
    granularity: Optional[str],
    year_min: Optional[int],
    year_max: Optional[int],
    reachable: bool,
    resource_format: Optional[str],
    enrich_method: str,
    needs_review: bool,
    source_status: Optional[str] = None,
) -> tuple[int, bool]:
    """Restituisce (score 0-100, intake_candidate)."""
    score = 0

    # granularità — 0..40
    score += _GRAN_SCORE.get(granularity or "non_determinato", 0)

    # copertura anni — 0..20 (lineare fino a _YEAR_SPAN_MAX anni)
    if year_min is not None and year_max is not None:
        span = max(0, year_max - year_min)
        score += min(20, int(span / _YEAR_SPAN_MAX * 20))
    elif year_min is not None or year_max is not None:
        score += 5  # almeno un anno noto

    # raggiungibile — 0..20
    score += 20 if reachable else 0

    # formato — 0..20 (normalizza: estrai estensione se il campo è un nome file)
    fmt_raw = ("" if not isinstance(resource_format, str) else resource_format).strip()
    if "." in fmt_raw and len(fmt_raw) > 6:
        fmt_raw = fmt_raw.rsplit(".", 1)[-1]
    fmt = fmt_raw.upper()
    score += _FORMAT_SCORE.get(fmt, 0)

    # qualità enrichment — 0..5 bonus, -5 penalità
    enrich_str = enrich_method if isinstance(enrich_method, str) else ""
    if enrich_str in ("ckan_package_show", "sdmx_dataflow_annotations"):
        score += 5
    if needs_review:
        score -= 5

    # penalità per source stale — fonte down, dati potrebbero essere outdated
    if source_status == "stale":
        score -= 10
        needs_review = True  # force review per stale

    score = max(0, min(100, score))
    candidate = score >= 40 and not needs_review

    return score, candidate


# ── core ──────────────────────────────────────────────────────────────────────

def _check_row(row: pd.Series, check_ts: str, registry: dict[str, Any], session: Optional[requests.Session] = None) -> dict:
    enrich = _enrich(row, registry, session=session)

    # granularità e anni: da enrichment, poi fallback su campi catalogo
    granularity = enrich["granularity"]
    year_min = enrich["year_min"]
    year_max = enrich["year_max"]
    if granularity == "non_determinato" or (granularity is None) or (year_min is None):
        fb_gran, fb_ymin, fb_ymax = _fallback_infer(row)
        if granularity in (None, "non_determinato"):
            granularity = fb_gran
        year_min = year_min or fb_ymin
        year_max = year_max or fb_ymax

    # URL da controllare: enrichment resource > catalogo landing_page > distribution_url
    url_to_check = (
        enrich.get("resource_url")
        or row.get("landing_page")
        or row.get("distribution_url")
    )
    # per SDMX la metadata_url non è un dato, usiamo la base_url per il check
    if enrich["enrich_method"] == "sdmx_dataflow_annotations":
        url_to_check = row.get("landing_page") or row.get("distribution_url")

    http_status, reachable, note = _http_head(url_to_check or "", session=session)

    return {
        "check_timestamp": check_ts,
        "source_id": row.get("source_id"),
        "item_id": row.get("item_id"),
        "item_name": row.get("item_name"),
        "title": enrich["enriched_title"] or row.get("title"),
        "organization": row.get("organization"),
        "tags": enrich["enriched_tags"] or row.get("tags"),
        "notes": enrich["enriched_notes"],
        "url_checked": url_to_check,
        "http_status": http_status,
        "reachable": reachable,
        "check_notes": note or None,
        "granularity": granularity,
        "year_min": year_min,
        "year_max": year_max,
        "resource_format": enrich["resource_format"] or row.get("format"),
        "enrich_method": enrich["enrich_method"],
        "source_status": row.get("source_status", "unknown"),
        "needs_review": (granularity == "non_determinato") or (year_min is None),
        "intake_score": None,  # placeholder, calcolato sotto
        "intake_candidate": None,
    }


def _finalize_scores(result: dict) -> dict:
    score, candidate = _intake_score(
        granularity=result.get("granularity"),
        year_min=result.get("year_min"),
        year_max=result.get("year_max"),
        reachable=result.get("reachable", False),
        resource_format=result.get("resource_format"),
        enrich_method=result.get("enrich_method", "none"),
        needs_review=result.get("needs_review", True),
        source_status=result.get("source_status"),
    )
    result["intake_score"] = score
    result["intake_candidate"] = candidate
    return result


def run_bulk_check(df: pd.DataFrame, workers: int = MAX_WORKERS) -> pd.DataFrame:
    registry = _load_registry()
    check_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = []

    # Shared session with connection pooling — reused across all HTTP calls in the pool.
    # Thread-safe for read-only usage: headers are set at creation and never mutated,
    # no cookies are modified, the adapter pool is append-only.
    # Do NOT add cookie/header mutations after creation — that would introduce races.
    session = get_pooled_session(pool_connections=16, pool_maxsize=32)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {pool.submit(_check_row, row, check_ts, registry, session): i for i, row in df.iterrows()}
        done = 0
        total = len(future_to_idx)
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            try:
                results.append(_finalize_scores(future.result()))
            except Exception as exc:
                logger.warning("Row check failed for index %d: %s", i, exc)
                results.append({"check_notes": f"check failed: {exc}", "enrich_method": "error"})
            done += 1
            if done % 50 == 0 or done == total:
                logger.info("  %d/%d completed", done, total)

    session.close()
    return pd.DataFrame(results)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in", dest="input", type=Path, default=DEFAULT_IN)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--source-ids", nargs="+", metavar="ID")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--limit-per-source", type=int, default=None, metavar="N",
                   help="Massimo N item per source_id (applicato prima del check)")
    p.add_argument("--workers", type=int, default=MAX_WORKERS)
    p.add_argument("--max-age-days", type=int, default=7,
                   help="Non ri-controllare item con check_timestamp più recente di N giorni (default: 7)")
    p.add_argument("--include-no-url", dest="only_with_url", action="store_false", default=True,
                   help="Includi anche item senza URL nel catalogo (verranno comunque arricchiti via API)")
    p.add_argument("--only-with-title", action="store_true", default=False,
                   help="Salta item senza title nel catalogo (tipicamente righe non-sample senza metadati)")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
    args = parse_args()

    logger.info("Loading catalog: %s", args.input)
    df = pd.read_parquet(args.input)
    logger.info("  %d total items", len(df))

    if args.source_ids:
        df = df[df["source_id"].isin(args.source_ids)]
        logger.info("  source_ids filter %s: %d items", args.source_ids, len(df))

    if args.only_with_url:
        has_url = df["landing_page"].notna() | df["distribution_url"].notna()
        df = df[has_url]
        logger.info("  URL present in catalog filter: %d items", len(df))

    if args.only_with_title:
        df = df[df["title"].notna()]
        logger.info("  non-null title filter: %d items", len(df))

    if args.limit:
        df = df.head(args.limit)
        logger.info("  limit %d: %d items", args.limit, len(df))

    if args.limit_per_source:
        df = df.groupby("source_id", group_keys=False).head(args.limit_per_source)
        logger.info("  limit-per-source %d: %d items", args.limit_per_source, len(df))

    if df.empty:
        logger.info("No items to check. Exiting.")
        return

    # ── Logica incrementale ──────────────────────────────────────────────────────
    existing = None
    skipped = 0
    if args.out.exists():
        logger.info("Loading previous results: %s", args.out)
        existing = pd.read_parquet(args.out)
        logger.info("  %d previous results", len(existing))

        # Parsare check_timestamp come datetime se presente
        if "check_timestamp" in existing.columns:
            existing["check_timestamp"] = pd.to_datetime(existing["check_timestamp"], utc=True)

        # Filtra item da non ri-controllare
        if "item_id" in existing.columns:
            now = pd.Timestamp.now(tz="UTC")
            cutoff = now - pd.Timedelta(days=args.max_age_days)

            # Trova gli item con check recente (più recente di cutoff)
            existing_recent = existing[existing["check_timestamp"] >= cutoff]
            recent_ids = set(str(x) for x in existing_recent["item_id"].astype(str).unique())

            # ── Secondo criterio: re-aggiungi item se la fonte ha aggiornato modified ──
            if "modified" in df.columns and not df.empty:
                # Prepara df per il merge
                df_modified = df[["item_id", "modified"]].copy()
                df_modified["item_id"] = df_modified["item_id"].astype(str)

                # Prepara existing_recent per il merge
                existing_for_merge = existing_recent[["item_id", "check_timestamp"]].copy()
                existing_for_merge["item_id"] = existing_for_merge["item_id"].astype(str)

                # Merge su item_id
                merge_df = pd.merge(
                    df_modified,
                    existing_for_merge,
                    on="item_id",
                    how="inner"
                )

                # Parsa modified come datetime
                merge_df["modified"] = pd.to_datetime(merge_df["modified"], utc=True, errors="coerce")

                # Filtra item dove modified > check_timestamp (e modified non è null)
                updated_mask = (merge_df["modified"].notna()) & (merge_df["modified"] > merge_df["check_timestamp"])
                updated_ids = set(merge_df[updated_mask]["item_id"].unique())

                # Rimuovi questi item da recent_ids (vanno ri-controllati)
                reinspected = len(recent_ids & updated_ids)
                if reinspected > 0:
                    recent_ids = recent_ids - updated_ids
                    logger.info("  %d items re-added because source updated modified", reinspected)

            # Filtra catalogo escludendo item recenti
            df_to_check = df[~df["item_id"].astype(str).isin(recent_ids)].copy()
            skipped = len(df) - len(df_to_check)

            if skipped > 0:
                logger.info("  Skipped %d items checked in last %d days", skipped, args.max_age_days)
            logger.info("  %d items to check", len(df_to_check))
            df = df_to_check
        else:
            logger.warning("  existing has no 'item_id' column, skipping dedup")

    if df.empty:
        logger.info("No new items to check. Exiting.")
        return

    logger.info("Starting check on %d items (%d workers)...", len(df), args.workers)
    t0 = time.time()
    results = run_bulk_check(df, workers=args.workers)
    elapsed = time.time() - t0
    logger.info("Completed in %.1fs", elapsed)

    # ── Upsert ───────────────────────────────────────────────────────────────────
    if existing is not None and not existing.empty and "item_id" in existing.columns:
        # Tieni solo i risultati da existing che non sono stati ri-controllati
        existing_to_keep = existing[~existing["item_id"].astype(str).isin(results["item_id"].astype(str))]

        # Concatena nuovi risultati con quelli vecchi (non ri-controllati)
        results = pd.concat([results, existing_to_keep], ignore_index=True)

        # Deduplica su item_id tenendo la riga con check_timestamp più recente
        results["check_timestamp"] = pd.to_datetime(results["check_timestamp"], utc=True)
        results = results.sort_values("check_timestamp", ascending=False).drop_duplicates(subset=["item_id"], keep="first").reset_index(drop=True)
        logger.info("  Unified %d results (new + previous not re-checked)", len(results))

    enrich_counts = results["enrich_method"].value_counts()
    reachable_n = results["reachable"].sum() if "reachable" in results.columns else 0
    reachable_pct = results["reachable"].mean() * 100 if "reachable" in results.columns else 0
    logger.info("Enrichment:\n%s", enrich_counts.to_string())
    logger.info("Reachable: %.0f%% (%d/%d)", reachable_pct, reachable_n, len(results))
    logger.info("Granularity:\n%s", results["granularity"].value_counts().to_string())
    logger.info("Needs review: %d", results["needs_review"].sum())
    if "intake_score" in results.columns:
        candidates = results["intake_candidate"].sum()
        avg_score = results["intake_score"].mean()
        logger.info("Intake candidates: %d/%d (avg score: %.0f)", candidates, len(results), avg_score)
        top = results[results["intake_candidate"].fillna(False)].nlargest(5, "intake_score")[["title","granularity","year_min","year_max","intake_score"]]
        if not top.empty:
            logger.info("Top candidates:\n%s", top.to_string(index=False))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    results.to_parquet(args.out, index=False)
    logger.info("Results: %s", args.out)


if __name__ == "__main__":
    main()
