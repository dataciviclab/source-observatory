"""
Utility condivise per validazione item per protocollo.

Usate dai collector CKAN, HTML, SDMX, SPARQL per validare
i propri item dopo l'enumerazione.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from lab_connectors.http import HttpClient

from scripts._constants import format_score as _format_score

_DEFAULT_TIMEOUT = 5
_SNIFF_BYTES = 32 * 1024


# ── URL selection per group ───────────────────────────────────────────────────


def pick_best_url(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick best URL from a group: prefer CSV > JSON > ZIP, recent year."""
    if not items:
        return None

    scored = []
    for item in items:
        url = item.get("distribution_url") or item.get("url") or ""
        if not url:
            continue
        fmt = item.get("format") or ""
        if not isinstance(fmt, str):
            fmt = ""
        year = item.get("year_signal") or item.get("year_max") or item.get("year_min")
        if isinstance(year, float) and year != year:  # NaN check
            year = 0
        score = _format_score(fmt) * 1000 + (year or 0)
        scored.append((score, item))

    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


# ── Reachability probe ────────────────────────────────────────────────────────


# Soglia circuit breaker: 3 fallimenti consecutivi sullo stesso host e il
# client smette di tentare la rete (CircuitOpenError immediato). Serve per
# non bruciare retry+timeout su host giu' ripetuti gruppo dopo gruppo
# (es. lavoro_opendata: 83 gruppi x ~11s = ~15min senza breaker).
CIRCUIT_THRESHOLD = 3


def probe_reachability(
    url: str,
    timeout: int = _DEFAULT_TIMEOUT,
    client: Any | None = None,
) -> dict[str, Any]:
    """HTTP HEAD probe, con fallback SSL.

    ``client`` opzionale: se fornito (es. dal validate che condivide un
    HttpClient con circuit breaker), viene riusato — il breaker resta
    attivo tra gruppi della stessa fonte. Altrimenti crea un client nuovo
    (comportamento storico).
    """
    result: dict[str, Any] = {
        "reachable": False,
        "status_code": None,
        "content_type": None,
        "error": None,
    }
    try:
        client = client or HttpClient(timeout=timeout)
        resp = client.head(url, verify=False)
        if resp.is_ok and resp.response is not None:
            result["reachable"] = True
            result["status_code"] = resp.response.status_code
            result["content_type"] = resp.response.headers.get("Content-Type")
        else:
            status = resp.response.status_code if resp.response else "?"
            result["error"] = str(resp.err) if resp.err else f"HTTP {status}"
    except Exception as e:
        result["error"] = str(e)
    return result


# ── CSV schema sniff ──────────────────────────────────────────────────────────


def _is_csv_url(url: str, content_type: str | None = None) -> bool:
    """Check if URL o Content-Type suggeriscono CSV."""
    if content_type:
        ct = content_type.lower()
        if "csv" in ct or "text/plain" in ct:
            return True
    return url.lower().endswith(".csv") or ".csv?" in url.lower()


# Nomi colonna che indicano una dimensione temporale (valori = anni)
_YEAR_COLUMN_HINTS = frozenset(
    {
        "anno",
        "year",
        "annual",
        "data",
        "date",
        "periodo",
        "period",
        "mese",
        "month",
        "time_period",
        "anno di riferimento",
        "anno di liquidazione",
        "anno tariffario",
        "anno di competenza",
    }
)


def _is_year_column(col: str) -> bool:
    """True se il nome colonna indica una dimensione temporale (anni)."""
    cl = col.lower().strip()
    return cl in _YEAR_COLUMN_HINTS or cl.startswith("anno") or "time_period" in cl


def _extract_year_range(
    raw: bytes | None,
    columns: list[str],
    sample: list[dict],
    url: str,
) -> tuple[int | None, int | None]:
    """Estrae range anni (min, max) da un CSV profilato.

    Ordine di tentativo:
    1. anni nei NOMI colonna (es. ``anno_2020``) — toolkit._extract_years_from_columns
    2. valori in una colonna-anno (es. colonna ``ANNO`` con valori 2018..2024):
       il sample dello sniff standard contiene stringhe, quindi serve DuckDB
       sul raw per avere valori tipizzati e range su tutto il sample
    3. anni nel filename (es. ``beneficiari_2007-2013.zip``) — toolkit._extract_years

    Ritorna (None, None) se non trova nulla.
    """
    from toolkit.profile.preview import _extract_years_from_columns
    from toolkit.scout.link_extractor import _extract_years as _filename_years

    # 1. anni da nomi colonna
    y_cols = _extract_years_from_columns(columns)
    if y_cols != (None, None):
        return y_cols

    # 2. anni da valori in colonna-anno (serve sample tipizzato via DuckDB)
    if raw and any(_is_year_column(col) for col in columns):
        duck = _sniff_csv_duckdb(raw, _SNIFF_BYTES)
        if duck.get("year_min") is not None:
            return (duck["year_min"], duck["year_max"])

    # 3. anni da filename
    y_file = _filename_years(url.split("?")[0])
    if y_file:
        return (min(y_file), max(y_file))

    return (None, None)


def _sniff_csv_duckdb(raw: bytes, sample_size: int) -> dict[str, Any]:
    """Fallback sniff via DuckDB read_csv.

    Il parser standard (csv.Sniffer + DictReader) fallisce su SDMX-CSV e su
    CSV con newline dentro campi non quotati ("new-line character seen in
    unquoted field") — DuckDB li gestisce. Usato solo quando il tentativo
    standard non produce colonne.
    """
    import tempfile

    import duckdb

    result: dict[str, Any] = {
        "columns": [],
        "num_columns": 0,
        "num_rows": 0,
        "delimiter": None,
        "encoding": "utf-8",
        "sample": [],
        "error": None,
    }
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            df = duckdb.sql(
                f"SELECT * FROM read_csv('{tmp_path}', header=true, sample_size=-1)"
            ).fetchdf()
            result["columns"] = list(df.columns)
            result["num_columns"] = len(df.columns)
            result["num_rows"] = len(df)
            result["delimiter"] = None  # DuckDB auto-detect; non esposto
            result["sample"] = df.head(5).to_dict("records")[:5]
            # Range anni dalla colonna-anno sull'intero sample (non solo 5 righe)
            ymin, ymax = _year_range_from_df(df)
            if ymin is not None:
                result["year_min"] = ymin
                result["year_max"] = ymax
        finally:
            import os

            os.unlink(tmp_path)
    except Exception as exc:
        result["error"] = f"duckdb fallback: {exc}"
    return result


def _year_range_from_df(df) -> tuple[int | None, int | None]:
    """Min/max anni dai valori della colonna-anno in un DataFrame DuckDB."""
    import math

    if df is None or len(df.columns) == 0:
        return (None, None)
    # trova la colonna-anno (nome hint o valori che sembrano anni)
    year_col: str | None = None
    for col in df.columns:
        cl = str(col).lower().strip()
        if cl in _YEAR_COLUMN_HINTS or cl.startswith("anno") or "time_period" in cl:
            year_col = col
            break
    if year_col is None:
        # fallback: colonna numerica con 2+ valori nel range 1900-2100
        for col in df.columns:
            vals = [
                int(v)
                for v in df[col].tolist()
                if isinstance(v, (int, float))
                and not (isinstance(v, float) and math.isnan(v))
                and 1900 <= v <= 2100
            ]
            if len(set(vals)) >= 2:
                year_col = col
                break
    if year_col is None:
        return (None, None)
    vals = [
        int(v)
        for v in df[year_col].tolist()
        if isinstance(v, (int, float))
        and not (isinstance(v, float) and math.isnan(v))
        and 1900 <= v <= 2100
    ]
    if not vals:
        return (None, None)
    return (min(vals), max(vals))


def sniff_csv_schema(
    url: str,
    timeout: int = _DEFAULT_TIMEOUT,
    client: Any | None = None,
) -> dict[str, Any]:
    """Download primi byte CSV e sniffa schema.

    ``client`` opzionale: se fornito, riusato (breaker condiviso tra
    gruppi). Altrimenti client nuovo (comportamento storico).

    Returns:
        columns, num_columns, num_rows, delimiter, encoding, sample, error
    """
    result: dict[str, Any] = {
        "columns": [],
        "num_columns": 0,
        "num_rows": 0,
        "delimiter": None,
        "encoding": None,
        "sample": [],
        "error": None,
    }
    try:
        client = client or HttpClient(timeout=timeout)
        # Range limitato: scarica solo primi KB (SDMX puo' essere enorme)
        resp = client.get(url, headers={"Range": f"bytes=0-{_SNIFF_BYTES}"}, verify=False)
        if not resp.is_ok or resp.response is None:
            result["error"] = str(resp.err) if resp.err else "Failed to fetch"
            return result

        raw = resp.response.content
        if not raw:
            result["error"] = "Empty response"
            return result

        encoding = "utf-8"
        if raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"

        text = raw.decode(encoding, errors="replace")[:_SNIFF_BYTES]

        try:
            dialect = csv.Sniffer().sniff(text[:4096])
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","

        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows = []
        columns = None
        for i, row in enumerate(reader):
            if i == 0:
                columns = list(row.keys())
            if i < 5:
                rows.append(row)
            if i >= 100:
                break

        if columns:
            result["columns"] = columns
            result["num_columns"] = len(columns)
        result["num_rows"] = i + 1 if columns else 0
        result["sample"] = rows
        result["delimiter"] = delimiter
        result["encoding"] = encoding

        # Fallback DuckDB: il parser standard fallisce su SDMX-CSV e CSV con
        # newline nei campi ("new-line character seen in unquoted field").
        # Se non ha prodotto colonne, prova DuckDB che li gestisce.
        if not columns:
            duck = _sniff_csv_duckdb(raw, _SNIFF_BYTES)
            if duck.get("columns"):
                result["columns"] = duck["columns"]
                result["num_columns"] = duck["num_columns"]
                result["num_rows"] = duck["num_rows"]
                result["sample"] = duck["sample"]
                result["sniff_fallback"] = "duckdb"
                result["error"] = None  # recuperato: errore standard superato
            elif duck.get("error"):
                result["sniff_error"] = duck["error"]

        # Estrazione range anni (min, max) da colonne/valori/filename.
        # Popola year_min/year_max quando la fonte non li fornisce gia'.
        if result.get("columns"):
            ymin, ymax = _extract_year_range(
                raw=raw,
                columns=result["columns"],
                sample=result.get("sample") or [],
                url=url,
            )
            if ymin is not None and ymax is not None:
                result["year_min"] = ymin
                result["year_max"] = ymax

    except Exception as e:
        result["error"] = str(e)

    return result


# ── Validazione standard per item tabulari (CKAN, HTML) ───────────────────────


def validate_tabular_group(
    items: list[dict[str, Any]],
    deep: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """Valida un gruppo di item tabulari (CKAN/HTML): HEAD + sniff CSV.

    Salta completamente i probe HTTP per gruppi non-CSV (ZIP, TTL, JSON...).
    Per gruppi CSV, sniff leggero interno (encoding, delim, colonne).

    Con ``deep=True``, usa toolkit.profile.preview.preview_url per profilo
    approfondito (tipi colonna, quality score, granularità, anni) — più
    lento ma più ricco.

    ``client`` opzionale: HttpClient condiviso tra gruppi (con circuit
    breaker attivo) — se fornito dalla pipeline, il breaker sopravvive
    tra gruppi della stessa run. Altrimenti ne crea uno per gruppo
    (comportamento storico, breaker non efficace tra gruppi).

    Usato da collectors.ckan.validate_items() e collectors.html.validate_items().
    """
    best = pick_best_url(items)
    if best is None:
        return {
            "dataset_group": items[0].get("dataset_group", "unknown"),
            "source_id": items[0].get("source_id", ""),
            "protocol": items[0].get("protocol", ""),
            "item_count": len(items),
            "reachable": False,
            "error": "No URL available",
        }

    url_raw = best.get("distribution_url") or best.get("url") or ""
    if not isinstance(url_raw, str):
        url_raw = ""
    url = url_raw.split("?")[0]
    fmt = best.get("format") or ""
    if not isinstance(fmt, str):
        fmt = ""
    is_csv = "csv" in fmt.lower() or url.lower().endswith(".csv")

    result: dict[str, Any] = {
        "dataset_group": best.get("dataset_group", "unknown"),
        "source_id": best.get("source_id", ""),
        "protocol": best.get("protocol", ""),
        "item_count": len(items),
        "url": url,
        "format": fmt,
        "reachable": False,
        "status_code": None,
        "content_type": None,
        "error": None,
    }

    # Propaga metadati del gruppo (dal merge)
    # Attenzione: il merge pandas produce NaN, non None — tratta entrambi come "assente".
    for col in ("dataset_group_size", "dataset_group_year_min", "dataset_group_year_max"):
        val = best.get(col)
        is_nan = isinstance(val, float) and val != val  # NaN
        if val is not None and not is_nan:
            result[col] = val

    # ── Non-CSV: salta completamente i probe HTTP ──────────────────────────
    if not is_csv:
        # Score minimale: 1 per formati comunque utilizzabili (json, xml, parquet)
        util_score = 1 if any(k in fmt.lower() for k in ("json", "xml", "parquet")) else 0
        result["note"] = f"Non-CSV format: {fmt}"
        result["reachable"] = None  # non verificato
        result["readiness_score"] = util_score
        return result

    # ── CSV: HEAD probe + sniff schema ─────────────────────────────────────
    # Client condiviso con circuit breaker: se un host fallisce 3 volte
    # consecutive, i gruppi successivi della stessa fonte non ritentano la
    # rete (CircuitOpenError immediato) — evita di bruciare ~11s per gruppo
    # su host giu' (es. lavoro_opendata: 83 gruppi -> ~15min senza breaker).
    # Se la pipeline passa un client condiviso, il breaker sopravvive tra
    # gruppi; altrimenti ne crea uno per gruppo (breaker solo intra-gruppo).
    http = client or HttpClient(timeout=_DEFAULT_TIMEOUT, circuit_threshold=CIRCUIT_THRESHOLD)
    probe = probe_reachability(url, timeout=_DEFAULT_TIMEOUT, client=http)
    result.update({k: v for k, v in probe.items()})

    if not result["reachable"]:
        result["readiness_score"] = 1  # reachable no: solo formato CSV
        return result

    # Sniff CSV: sniff leggero interno.
    schema = sniff_csv_schema(url, timeout=_DEFAULT_TIMEOUT, client=http)
    result["columns"] = schema["columns"]
    result["num_columns"] = schema["num_columns"]
    result["num_sample_rows"] = schema["num_rows"]
    result["delimiter"] = schema["delimiter"]
    result["encoding"] = schema["encoding"]
    if schema["error"]:
        result["sniff_error"] = schema["error"]

    # Anni: se il gruppo non li forniva gia' (year_signal da collector),
    # usa il range estratto dallo sniff (colonne/valori/filename).
    # Attenzione: il merge pandas produce NaN, non None — tratta entrambi come "assente".
    ymin_cur = result.get("dataset_group_year_min")
    missing = ymin_cur is None or (
        isinstance(ymin_cur, float) and ymin_cur != ymin_cur  # NaN
    )
    if missing and schema.get("year_min") is not None:
        result["dataset_group_year_min"] = schema["year_min"]
        result["dataset_group_year_max"] = schema["year_max"]

    # readiness_score 0-10
    score = 0
    if result.get("reachable"):
        score += 2  # raggiungibile
    if is_csv:
        score += 2  # formato aperto
    if result.get("num_columns", 0) >= 3:
        score += 2  # abbastanza colonne per essere informativo
    elif result.get("num_columns", 0) > 0:
        score += 1
    if result.get("status_code") == 200:
        score += 1  # HTTP ok
    if schema.get("delimiter"):
        score += 1  # CSV parsabile
    if schema.get("encoding") in ("utf-8", "utf-8-sig"):
        score += 1  # encoding standard
    if result.get("dataset_group_year_min") is not None:
        score += 1  # anni noti

    # Penalità: sniff fallito su falso CSV (es. XLSX spacciato per CSV)
    if schema.get("error") and result.get("num_columns", 0) == 0:
        score = max(0, score - 3)
    # Penalità: content-type non CSV (es. application/vnd.ms-excel)
    ct = (result.get("content_type") or "").lower()
    if ct and "csv" not in ct and "text/plain" not in ct and "text/" not in ct:
        score = max(0, score - 1)

    result["readiness_score"] = score

    return result
