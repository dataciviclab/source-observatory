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


def probe_reachability(url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """HTTP HEAD probe, con fallback SSL."""
    result: dict[str, Any] = {
        "reachable": False,
        "status_code": None,
        "content_type": None,
        "error": None,
    }
    try:
        client = HttpClient(timeout=timeout)
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


def sniff_csv_schema(url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Download primi byte CSV e sniffa schema.

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
        client = HttpClient(timeout=timeout)
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

    except Exception as e:
        result["error"] = str(e)

    return result


# ── Validazione standard per item tabulari (CKAN, HTML) ───────────────────────


def validate_tabular_group(
    items: list[dict[str, Any]],
    deep: bool = False,
) -> dict[str, Any]:
    """Valida un gruppo di item tabulari (CKAN/HTML): HEAD + sniff CSV.

    Salta completamente i probe HTTP per gruppi non-CSV (ZIP, TTL, JSON...).
    Per gruppi CSV, sniff leggero interno (encoding, delim, colonne).

    Con ``deep=True``, usa toolkit.profile.preview.preview_url per profilo
    approfondito (tipi colonna, quality score, granularità, anni) — più
    lento ma più ricco.

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
    for col in ("dataset_group_size", "dataset_group_year_min", "dataset_group_year_max"):
        val = best.get(col)
        if val is not None:
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
    probe = probe_reachability(url)
    result.update({k: v for k, v in probe.items()})

    if not result["reachable"]:
        result["readiness_score"] = 1  # reachable no: solo formato CSV
        return result

    # Sniff CSV: sniff leggero interno.
    schema = sniff_csv_schema(url)
    result["columns"] = schema["columns"]
    result["num_columns"] = schema["num_columns"]
    result["num_sample_rows"] = schema["num_rows"]
    result["delimiter"] = schema["delimiter"]
    result["encoding"] = schema["encoding"]
    if schema["error"]:
        result["sniff_error"] = schema["error"]

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
