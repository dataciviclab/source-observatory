"""
Analyze fase per bulk source-check.

Funzioni di analisi pura (nessuna dipendenza HTTP o I/O).
Le inferenze pure (anni, granularità) ora vengono da toolkit.scout.infer.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import pandas as pd
from _constants import (
    JOIN_KEY_PATTERNS,
    JOIN_KEY_WEIGHTS,
    compute_joinability_score,
    detect_join_keys,
    parse_columns,
)
from toolkit.scout.infer import infer_granularity as _infer_granularity
from toolkit.scout.infer import infer_granularity_from_name_and_columns as _infer_gran_cols
from toolkit.scout.infer import infer_years as _infer_years

# ── dataset grouping ──────────────────────────────────────────────────────────


def _normalize_title_for_grouping(title: str) -> str:
    """Normalize a title to extract the conceptual dataset core.

    Strips trailing/leading years, date patterns, version suffixes, and
    format indicators so that items differing only by temporal slice get
    the same normalized key.

    Examples::

        "Population - 2022"                       -> "population"
        "Population - Years 2020-2025"            -> "population"
        "Redditi fisco 2023"                      -> "redditi fisco"
        "2023 Redditi fisco"                      -> "redditi fisco"
        "Accordi_pa_privati_dal_2010_al_2025"     -> "accordi_pa_privati"
        "provvedimenti_qualita_AIFA-2021_24.02.2022" -> "provvedimenti_qualita_aifa"
    """
    if not title or not isinstance(title, str):
        return ""
    t = title.lower().strip()

    # 0. Normalize underscore before 4-digit year sequences (so that regexes
    #    expecting \s* before years also match "_2022" or "_2010_al_2025").
    t = re.sub(r"_(\d{4})", r" \1", t)
    t = re.sub(r"(\d{4})_", r"\1 ", t)

    # 1. Parenthetical years: "(2022)", "(anni 2020-2025)"
    t = re.sub(r"\s*\(\s*(?:anni?\s*)?\d{4}\s*[-–]?\s*\d{0,4}\s*\)\s*$", "", t)

    # 2. Date-like patterns at end: "24.02.2022", "_24.02.2022", "30-10-2025" (FULL dates, before year stripping)
    t = re.sub(r"[\s_]*\d{1,2}[-./]\d{1,2}[-./]\d{4}\s*$", "", t)

    # 3. Years with descriptive text: "Years 2020-2025", "dal 2010 al 2025", "anni 2020-2025"
    #    Must be before bare year ranges to catch text prefix.
    #    Underscore before the prefix (e.g. "_dal_2010_al_2025") is also a separator.
    t = re.sub(
        r"[\s_][-–,;]?\s*(?:years|year|anni|anno|periodo|serie\s*storica|dal)\s+"
        r"[-–]?\s*\d{4}\s*[-–toal]*\s*\d{0,4}\s*$",
        "",
        t,
    )

    # 4. Trailing year range with comma or dash: "2011, 2015", "2022-2023", "2024-2050"
    t = re.sub(r"\s*[-–,;]?\s*\d{4}\s*[-–,;\s]\s*\d{4}\s*$", "", t)

    # 5. Trailing _YYYY suffix (common in INPS/MEF items): "cla_2017", "redditi_2023"
    t = re.sub(r"_\d{4}\s*$", "", t)

    # 6. Standalone trailing year: "2022"
    t = re.sub(r"\s*[-–,;]?\s*\d{4}\s*$", "", t)

    # 7. Leading year patterns: "2023 Redditi fisco", "2009 trasparenza"
    t = re.sub(r"^\d{4}\s*[-–]?\s*\d{0,4}[\s,;]+\s*", "", t)

    # 7b. Clean trailing hyphens, underscores, or space-digit leftovers
    #     (e.g. "-2021" after "_24.02.2022" was stripped)
    t = re.sub(r"[-–_]+\s*\d*\s*$", "", t)

    # 8. Trailing format indicators: " - csv", "_rdf", ".xml"
    t = re.sub(
        r"\s*[-–_]\s*(?:csv|xls|xlsx|json|zip|parquet|rdf|xml)\s*$", "", t, flags=re.IGNORECASE
    )
    t = re.sub(r"\.(?:csv|xls|xlsx|json|zip|parquet|rdf|xml)\s*$", "", t, flags=re.IGNORECASE)

    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # Strip trailing punctuation and separators
    t = t.rstrip(".,;:-–_ ")
    return t


def _to_slug(text: str, max_len: int = 80) -> str:
    """Convert free text to a filesystem-safe slug."""
    if not text:
        return "unknown"
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")[:max_len]


def compute_dataset_group(
    source_id: str,
    title: str | None,
    item_id: str | None,
    protocol: str | None = None,
) -> str:
    """Compute a ``dataset_group`` slug that groups multi-year / multi-version
    items representing the same conceptual dataset.

    Strategy (first match wins):

    1.  **Normalized title** — if a meaningful title exists, strip years
        and slugify.  This is the most reliable signal.
    2.  **SDMX prefix** — for SDMX items, strip the trailing ``_\\d+``
        version suffix from the item_id to get the conceptual dataflow.
    3.  **item_id fallback** — use the item_id itself.
    4.  **unknown** — ``{source_id}/unknown``.
    """
    # Strategy 1: normalized title
    if title and isinstance(title, str) and len(title.strip()) > 5:
        norm = _normalize_title_for_grouping(title)
        if norm and len(norm) > 3:
            slug = _to_slug(norm)
            return f"{source_id}/{slug}"[:120]

    # Strategy 2: SDXM — strip trailing version suffix
    if item_id:
        iid = str(item_id)
        if protocol == "sdmx":
            core = re.sub(r"_\d+$", "", iid)
            if len(core) > 5:
                return f"{source_id}/sdmx/{_to_slug(core)}"[:120]
        # Strategy 3: plain item_id
        if len(iid) > 3:
            return f"{source_id}/{_to_slug(iid)}"[:120]

    return f"{source_id}/unknown"


def add_dataset_group_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``dataset_group``, ``dataset_group_size``, ``dataset_group_year_min``,
    and ``dataset_group_year_max`` columns to a source-check results DataFrame.

    This is called right before writing the parquet (after the upsert merge)
    so the parquet carries grouping metadata permanently.
    """
    df = df.copy()

    # Ensure year_min/year_max exist (may be missing in error fallback rows)
    for col in ("year_min", "year_max"):
        if col not in df.columns:
            df[col] = None

    # Compute group for each row
    df["dataset_group"] = df.apply(
        lambda r: compute_dataset_group(
            source_id=str(r.get("source_id", "")),
            title=r.get("title"),
            item_id=str(r.get("item_id", "")),
            protocol=str(r.get("protocol", "")) if "protocol" in r.index else None,
        ),
        axis=1,
    )

    # Group-wise aggregations
    group_agg = (
        df.groupby("dataset_group")
        .agg(
            dataset_group_size=("item_id", "count"),
            dataset_group_year_min=("year_min", "min"),
            dataset_group_year_max=("year_max", "max"),
        )
        .reset_index()
    )

    # Merge back
    df = df.merge(group_agg, on="dataset_group", how="left")
    return df


# ── CKAN analysis ─────────────────────────────────────────────────────────────


def _parse_ckan_package(pkg: dict) -> dict:
    """Estrae i campi utili da un package CKAN."""
    tags = [
        (t.get("display_name") or t.get("name") or "")
        for t in (pkg.get("tags") or [])
        if isinstance(t, dict)
    ]

    groups = [
        (g.get("display_name") or g.get("name") or "")
        for g in (pkg.get("groups") or [])
        if isinstance(g, dict)
    ]

    resources = pkg.get("resources") or []
    resource_url = None
    resource_format = None
    # Preferisci risorse con URL diretto a file (CSV/XLSX/XLS/JSON/ZIP)
    _FILE_EXTS = (".csv", ".xlsx", ".xls", ".json", ".zip", ".parquet", ".xml")
    direct_url = None
    direct_fmt = None
    for res in resources:
        u = res.get("url") or ""
        if not u.startswith("http"):
            continue
        low_url = u.lower()
        if any(ext in low_url for ext in _FILE_EXTS):
            direct_url = u
            direct_fmt = res.get("format") or None
            break
        if resource_url is None:
            resource_url = u
            resource_format = res.get("format") or None
    # Se trovato URL diretto, usalo; altrimenti usa il primo URL HTTP
    if direct_url:
        resource_url = direct_url
        resource_format = direct_fmt

    extras = {e["key"]: e["value"] for e in (pkg.get("extras") or []) if isinstance(e, dict)}
    temporal_start = extras.get("temporal_coverage_from") or extras.get("issued")
    temporal_end = extras.get("temporal_coverage_to") or extras.get("modified")

    if temporal_start is None and temporal_end is None:
        periodo = extras.get("Periodo di riferimento") or extras.get("periodo di riferimento")
        if periodo:
            ymin, ymax = _infer_years(str(periodo))
            if ymin is not None and ymax is not None:
                temporal_start, temporal_end = str(ymin), str(ymax)

    notes = (pkg.get("notes") or "").strip()
    title = pkg.get("title") or None

    combined = " ".join(filter(None, [title, ", ".join(groups), ", ".join(tags), notes[:500]]))
    granularity = _infer_granularity(combined)

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


# ── fallback euristica ────────────────────────────────────────────────────────


def _fallback_infer(row: pd.Series) -> tuple[str, Optional[int], Optional[int]]:
    parts = []
    for col in ("title", "tags", "notes_excerpt", "prefix", "url"):
        v = row.get(col)
        if v and str(v) not in ("nan", "None", ""):
            parts.append(str(v))
    combined = " ".join(parts)
    return _infer_granularity(combined), *_infer_years(combined)


# ── joinability scoring ──────────────────────────────────────────────────────
# I pattern, i pesi, e le funzioni di join key sono in _constants.py.
# source_check_analyze li ri-importa per backward compat interna.
# Il cross-ref con clean_catalog.json è demandato a joinability_scan.py.

_JOIN_KEY_PATTERNS = JOIN_KEY_PATTERNS  # type: ignore[assignment]
_JOIN_KEY_WEIGHTS = JOIN_KEY_WEIGHTS
_parse_columns = parse_columns
detect_join_keys = detect_join_keys  # type: ignore[assignment]
compute_joinability_score = compute_joinability_score  # type: ignore[assignment]


# ── intake scoring ────────────────────────────────────────────────────────────


_GRAN_SCORE = {
    "comune": 40,
    "provincia": 30,
    "regione": 20,
    "nazionale": 10,
    "europeo": 5,
    "non_determinato": 0,
}
_FORMAT_SCORE = {"CSV": 20, "JSON": 20, "XLSX": 12, "XLS": 10, "XML": 8, "SDMX": 8, "PDF": 2}
_YEAR_SPAN_MAX = 20


def _normalize_format(raw: str) -> str:
    if not isinstance(raw, str):
        return ""
    valid_priority = ["CSV", "JSON", "XLSX", "XLS", "XML", "PDF", "SDMX", "ZIP", "PARQUET"]
    up = raw.upper()
    for v in valid_priority:
        if v in up:
            return v
    return ""


def _intake_score(
    granularity: Optional[str],
    year_min: Optional[int],
    year_max: Optional[int],
    reachable: bool,
    resource_format: Optional[str],
    enrich_method: str,
    needs_review: bool,
    source_status: Optional[str] = None,
    encoding_suggested: Optional[str] = None,
    mapping_suggestions: Optional[str] = None,
    robust_read_suggested: Optional[bool] = None,
    delim_suggested: Optional[str] = None,
) -> tuple[int, bool]:
    score = 0
    score += _GRAN_SCORE.get(granularity or "non_determinato", 0)

    if year_min is not None and year_max is not None:
        span = max(0, year_max - year_min)
        score += min(20, int(span / _YEAR_SPAN_MAX * 20))
    elif year_min is not None or year_max is not None:
        score += 5

    score += 20 if reachable else 0

    fmt_raw = ("" if not isinstance(resource_format, str) else resource_format).strip()
    fmt = ""
    if fmt_raw:
        valid = ["CSV", "JSON", "XLSX", "XLS", "XML", "PDF", "SDMX", "ZIP", "PARQUET"]
        if "." in fmt_raw and len(fmt_raw) > 6:
            fmt_ext = fmt_raw.rsplit(".", 1)[-1].upper()
            if fmt_ext in valid:
                fmt = fmt_ext
        else:
            up = fmt_raw.upper()
            for v in valid:
                if v in up:
                    fmt = v
                    break
    score += _FORMAT_SCORE.get(fmt, 0)

    enrich_str = enrich_method if isinstance(enrich_method, str) else ""
    if enrich_str in ("ckan_package_show", "sdmx_dataflow_annotations"):
        score += 5
    if needs_review:
        score -= 5

    if source_status == "stale":
        score -= 10
        needs_review = True

    # Segnali di qualita' reali dal toolkit profiler
    if encoding_suggested:
        score += 5  # file esiste, encoding rilevato == leggibile e parsabile
    if delim_suggested:
        score += 2  # delimitatore rilevato (formato strutturato)
    if robust_read_suggested:
        score -= 10  # CSV sporco (righe irregolari, padding necessario)
        needs_review = True

    # mapping_suggestions: JSON con colonne → dati ben strutturati
    if mapping_suggestions:
        try:
            ms = (
                json.loads(mapping_suggestions)
                if isinstance(mapping_suggestions, str)
                else mapping_suggestions
            )
            if isinstance(ms, dict) and len(ms) >= 2:
                score += 5  # almeno 2 colonne con tipo inferito
            elif isinstance(ms, dict) and len(ms) >= 1:
                score += 3  # almeno 1 colonna
        except Exception:
            pass

    score = max(0, min(100, score))
    candidate = score >= 40 and not needs_review
    return score, candidate


def _infer_sdmx_join_keys(result: dict) -> dict[str, list[str]]:
    """Inferisce join keys dalle metadata SDMX quando non ci sono colonne profilate.

    SDMX non ha file CSV scaricabili, ma le dimensioni del dataflow
    (territorio, tempo, sesso, età, cittadinanza, mese) sono deducibili
    dai campi `granularity`, `year_min`/`year_max`, `tags` e `notes`.
    """
    found: dict[str, list[str]] = {}
    combined = ""

    tags = result.get("tags")
    if tags and isinstance(tags, str):
        combined += " " + tags.lower()
    notes = result.get("notes")
    if notes and isinstance(notes, str):
        combined += " " + notes.lower()
    title = result.get("title")
    if title and isinstance(title, str):
        combined += " " + title.lower()
    sdmx_flow = result.get("sdmx_flow")
    if sdmx_flow and isinstance(sdmx_flow, str):
        combined += " " + sdmx_flow.lower()

    # ── Chiave territoriale da granularity ──
    gran = result.get("granularity")
    if gran == "comune":
        found["istat_comune"] = ["REF_AREA"]
    elif gran == "provincia":
        found["provincia"] = ["REF_AREA"]
    elif gran == "regione":
        found["istat_regione"] = ["REF_AREA"]

    # ── Chiave temporale ──
    if result.get("year_min") is not None or result.get("year_max") is not None:
        found["anno"] = ["TIME_PERIOD"]

    # ── Chiavi demografiche da keywords ──
    if re.search(r"(?i)(sesso|sex|gender)", combined):
        found["sesso"] = ["SEX"]
    # age con word boundary — evita falsi positivi come wage, damage
    if re.search(r"(?i)(età|eta'|\bage\b|classe_eta|fascia_eta)", combined):
        found["eta"] = ["AGE"]
    if re.search(r"(?i)(cittadinanza|citizenship|nazionalit)", combined):
        found["cittadinanza"] = ["CITIZENSHIP"]
    # "paese" da solo è troppo generico (paese geografico)
    if re.search(r"(?i)\bpaese di cittadinanza\b", combined):
        found["cittadinanza"] = ["CITIZENSHIP"]
    if re.search(r"(?i)(mese|month)", combined):
        found["mese"] = ["TIME_FORMAT"]

    return found


def _finalize_scores(result: dict) -> dict:
    # ── Granularità: se non determinata, prova dalle colonne profilate ──────
    # Usa la funzione del toolkit (migliorata) che controlla i nomi colonna
    # individualmente prima del fallback regex.
    if result.get("granularity") in ("non_determinato", None):
        cols_raw = result.get("columns")
        if cols_raw:
            col_names = _parse_columns(cols_raw)
            if col_names:
                title = result.get("title") or ""
                inferred = _infer_gran_cols(title, col_names)
                if inferred and inferred != "non_determinato":
                    result["granularity"] = inferred
                    if result.get("year_min") is not None:
                        result["needs_review"] = False

    score, candidate = _intake_score(
        granularity=result.get("granularity"),
        year_min=result.get("year_min"),
        year_max=result.get("year_max"),
        reachable=result.get("reachable", False),
        resource_format=result.get("resource_format"),
        enrich_method=result.get("enrich_method", "none"),
        needs_review=result.get("needs_review", True),
        source_status=result.get("source_status"),
        encoding_suggested=result.get("encoding_suggested"),
        mapping_suggestions=result.get("mapping_suggestions"),
        robust_read_suggested=result.get("robust_read_suggested"),
        delim_suggested=result.get("delim_suggested"),
    )
    result["intake_score"] = score
    result["intake_candidate"] = candidate

    # ── Joinability: detect join keys from profiled columns ──────────────────
    # join_keys salva il mapping completo {chiave: [colonne_matched]} per
    # consentire a joinability_scan.py di fare cross-reference accurato.
    columns_raw = result.get("columns")
    found_keys = detect_join_keys(columns_raw)

    # ── SDMX fallback: se nessuna colonna profilata, inferisci dalle metadata ──
    if not found_keys and result.get("resource_format") == "SDMX":
        found_keys = _infer_sdmx_join_keys(result)

    result["join_keys"] = json.dumps(found_keys) if found_keys else None
    result["joinability_score"] = compute_joinability_score(found_keys)

    return result
