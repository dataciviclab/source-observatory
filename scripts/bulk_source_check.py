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
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collectors.base import observatory_get, observatory_head

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

_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20[012]\d)(?!\d)")

def _infer_years(text: str) -> tuple[Optional[int], Optional[int]]:
    years = [int(y) for y in _YEAR_RE.findall(text)]
    if not years:
        return None, None
    return min(years), max(years)


# ── HTTP check ────────────────────────────────────────────────────────────────

def _http_head(url: str) -> tuple[Optional[int], bool, str]:
    if not isinstance(url, str) or not url.startswith("http"):
        return None, False, "url_missing_or_invalid"
    # codifica spazi e caratteri non ASCII nell'URL preservando la struttura
    from urllib.parse import urlsplit, urlunsplit, quote
    parts = urlsplit(url)
    url = urlunsplit(parts._replace(path=quote(parts.path, safe="/:@!$&'()*+,;=")))
    try:
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

def _fetch_ckan_package(base_api: str, item_name: str) -> Optional[dict]:
    url = f"{base_api}/package_show?id={item_name}"
    try:
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

def _fetch_sdmx_years(base_url: str, flow_id: str) -> tuple[Optional[int], Optional[int]]:
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
        r = observatory_get(url, timeout=20)
        if r.status_code != 200:
            return None, None
        root = ET.fromstring(r.content)
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


def _fetch_sdmx_dataflow(base_url: str, flow_id: str) -> Optional[ET.Element]:
    # rimuovi query string e normalizza
    base = base_url.split("?")[0].rstrip("/")
    # risali alla root se l'url punta al listing completo
    if base.endswith("/IT1"):
        root_url = base
    else:
        root_url = base.rsplit("/", 1)[0]
    url = f"{root_url}/{flow_id}"
    try:
        r = observatory_get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return ET.fromstring(r.content)
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

def _fetch_html_metadata(url: str) -> dict:
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
        resp = observatory_get(url, timeout=10, stream=False)
        resp.raise_for_status()

        # Limita a 200KB
        content_length = len(resp.content)
        if content_length > 200000:
            resp.close()
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "html_scrape_failed"
            return result

        html = resp.text

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


def _enrich(row: pd.Series, registry: dict[str, Any]) -> dict:
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

    if protocol == "ckan" and base_url and item_name:
        # usa api_base_url pre-calcolata dal layer 1 (gestisce endpoint non-standard come INPS /odapi/)
        api_base_url = row.get("api_base_url")
        base_api = api_base_url if isinstance(api_base_url, str) and api_base_url.startswith("http") else base_url
        pkg = _fetch_ckan_package(base_api, item_name)
        if pkg:
            return _parse_ckan_package(pkg)

    if protocol == "sdmx" and base_url and item_name:
        sdmx_base = base_url
        # usa api_base_url pre-calcolata se disponibile
        api_base_url = row.get("api_base_url")
        if isinstance(api_base_url, str) and api_base_url.startswith("http"):
            sdmx_base = api_base_url
        xml_root = _fetch_sdmx_dataflow(sdmx_base, item_name)
        if xml_root is not None:
            return _parse_sdmx_annotations(xml_root, sdmx_base, item_name)

    # HTML fallback per fonti con solo landing_page (es. dati_camera)
    landing = row.get("landing_page")
    if isinstance(landing, str) and landing.startswith("http"):
        # salta se la fonte è nota per bloccare lo scraping
        if source_cfg.get("scraping_blocked"):
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "scraping_blocked"
            return result
        return _fetch_html_metadata(landing)

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

    score = max(0, min(100, score))
    candidate = score >= 40 and not needs_review

    return score, candidate


# ── core ──────────────────────────────────────────────────────────────────────

def _check_row(row: pd.Series, check_ts: str, registry: dict[str, Any]) -> dict:
    enrich = _enrich(row, registry)

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

    http_status, reachable, note = _http_head(url_to_check or "")

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
    )
    result["intake_score"] = score
    result["intake_candidate"] = candidate
    return result


def run_bulk_check(df: pd.DataFrame, workers: int = MAX_WORKERS) -> pd.DataFrame:
    registry = _load_registry()
    check_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check_row, row, check_ts, registry): i for i, row in df.iterrows()}
        done = 0
        total = len(futures)
        for future in as_completed(futures):
            try:
                results.append(_finalize_scores(future.result()))
            except Exception as exc:
                results.append({"check_notes": str(exc)[:200], "enrich_method": "error"})
            done += 1
            if done % 50 == 0 or done == total:
                print(f"  {done}/{total} completati")

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
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Carico catalogo: {args.input}")
    df = pd.read_parquet(args.input)
    print(f"  {len(df)} item totali")

    if args.source_ids:
        df = df[df["source_id"].isin(args.source_ids)]
        print(f"  filtro source_ids {args.source_ids}: {len(df)} item")

    if args.only_with_url:
        has_url = df["landing_page"].notna() | df["distribution_url"].notna()
        df = df[has_url]
        print(f"  filtro URL presenti nel catalogo: {len(df)} item")

    if args.limit:
        df = df.head(args.limit)
        print(f"  limit {args.limit}: {len(df)} item")

    if args.limit_per_source:
        df = df.groupby("source_id", group_keys=False).head(args.limit_per_source)
        print(f"  limit-per-source {args.limit_per_source}: {len(df)} item")

    if df.empty:
        print("Nessun item da controllare. Uscita.")
        return

    # ── Logica incrementale ──────────────────────────────────────────────────────
    existing = None
    skipped = 0
    if args.out.exists():
        print(f"\nCarico risultati precedenti: {args.out}")
        existing = pd.read_parquet(args.out)
        print(f"  {len(existing)} risultati precedenti")

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
                    print(f"  {reinspected} item ri-aggiunti perché la fonte ha aggiornato modified")

            # Filtra catalogo escludendo item recenti
            df_to_check = df[~df["item_id"].astype(str).isin(recent_ids)].copy()
            skipped = len(df) - len(df_to_check)

            if skipped > 0:
                print(f"  Saltati {skipped} item controllati negli ultimi {args.max_age_days} giorni")
            print(f"  {len(df_to_check)} item da controllare")
            df = df_to_check
        else:
            print("  Attenzione: existing non ha colonna 'item_id', saltando dedup")

    if df.empty:
        print("Nessun item nuovo da controllare. Uscita.")
        return

    print(f"\nAvvio check su {len(df)} item ({args.workers} workers)...")
    t0 = time.time()
    results = run_bulk_check(df, workers=args.workers)
    elapsed = time.time() - t0
    print(f"Completato in {elapsed:.1f}s")

    # ── Upsert ───────────────────────────────────────────────────────────────────
    if existing is not None and not existing.empty and "item_id" in existing.columns:
        # Tieni solo i risultati da existing che non sono stati ri-controllati
        existing_to_keep = existing[~existing["item_id"].astype(str).isin(results["item_id"].astype(str))]

        # Concatena nuovi risultati con quelli vecchi (non ri-controllati)
        results = pd.concat([results, existing_to_keep], ignore_index=True)

        # Deduplica su item_id tenendo la riga con check_timestamp più recente
        results["check_timestamp"] = pd.to_datetime(results["check_timestamp"], utc=True)
        results = results.sort_values("check_timestamp", ascending=False).drop_duplicates(subset=["item_id"], keep="first").reset_index(drop=True)
        print(f"  Unificati {len(results)} risultati (nuovi + precedenti non ri-controllati)")

    enrich_counts = results["enrich_method"].value_counts()
    reachable_n = results["reachable"].sum() if "reachable" in results.columns else 0
    reachable_pct = results["reachable"].mean() * 100 if "reachable" in results.columns else 0
    print(f"\nArricchimento:\n{enrich_counts.to_string()}")
    print(f"Raggiungibili: {reachable_pct:.0f}% ({reachable_n}/{len(results)})")
    print(f"Granularità:\n{results['granularity'].value_counts().to_string()}")
    print(f"Needs review: {results['needs_review'].sum()}")
    if "intake_score" in results.columns:
        candidates = results["intake_candidate"].sum()
        avg_score = results["intake_score"].mean()
        print(f"Intake candidates: {candidates}/{len(results)} (score medio: {avg_score:.0f})")
        top = results[results["intake_candidate"].fillna(False)].nlargest(5, "intake_score")[["title","granularity","year_min","year_max","intake_score"]]
        if not top.empty:
            print(f"\nTop candidati:\n{top.to_string(index=False)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    results.to_parquet(args.out, index=False)
    print(f"\nRisultati: {args.out}")


if __name__ == "__main__":
    main()
