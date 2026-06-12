"""Costanti condivise tra gli script di source-observatory.

Le costanti di path sono importate da ``so_mcp._paths`` (unica fonte).
Le utility (validate_schema, stale_reason, load/save) rimangono qui.

``so_mcp`` e' un package installato — import diretto, nessun sys.path hack.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from so_mcp._paths import (
    CATALOG_INVENTORY_DIR_PATH as CATALOG_INVENTORY_DIR_PATH,  # noqa: F401 — re‑export per scripts
)
from so_mcp._paths import (
    CATALOG_INVENTORY_REPORT_PATH as CATALOG_INVENTORY_REPORT_PATH,  # noqa: F401
)
from so_mcp._paths import (
    CATALOG_SIGNALS_PATH as CATALOG_SIGNALS_PATH,  # noqa: F401
)
from so_mcp._paths import (
    CHECK_PARQUET_PATH as CHECK_PARQUET_PATH,  # noqa: F401
)
from so_mcp._paths import (
    INVENTORY_PARQUET_PATH as INVENTORY_PARQUET_PATH,  # noqa: F401
)
from so_mcp._paths import (
    RADAR_HISTORY_PATH as RADAR_HISTORY_PATH,  # noqa: F401
)
from so_mcp._paths import (
    RADAR_SUMMARY_PATH as RADAR_SUMMARY_PATH,  # noqa: F401
)
from so_mcp._paths import (
    REGISTRY_PATH as REGISTRY_PATH,  # noqa: F401
)
from so_mcp._paths import (
    STATUS_MD_PATH as STATUS_MD_PATH,  # noqa: F401
)

# Repo root per path non esportati da so_mcp._paths (solo script).
_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Paths non esportati da so_mcp._paths (solo script) ─────────────────────
CATALOG_WATCH_REPORT_PATH = _REPO_ROOT / "data" / "catalog" / "CATALOG_WATCH_REPORT.md"
SCHEMA_DIR_PATH = _REPO_ROOT / "schemas"


def validate_schema(instance: dict, schema_name: str) -> None:
    """Validate a dict against the JSON schema file in schemas/."""
    schema_path = SCHEMA_DIR_PATH / schema_name
    if not schema_path.exists():
        print(f"⚠️  Schema {schema_name} non trovato — skip validazione")
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        print(f"❌ Validazione fallita ({schema_name}): {exc.message}")
        raise


# Canonical stale_reason taxonomy for catalog-inventory error classification.
# Used by build_catalog_inventory.py to tag stale rows.
STALE_REASON_TAGS = {
    "source_500": "HTTP 500 — Internal Server Error",
    "source_503": "HTTP 503 — Service Unavailable",
    "timeout": "Connection or application timeout",
    "ssl_error": "SSL/TLS handshake failure",
    "connection_error": "TCP connection failed",
    "dns_error": "DNS resolution failed",
    "unknown": "Unclassified error",
}


def stale_reason_from_exception(exc: Exception) -> str:
    """Map an exception to a canonical stale_reason tag."""
    msg = str(exc).lower()
    if "500" in msg or "internal server error" in msg:
        return "source_500"
    if "503" in msg or "service unavailable" in msg:
        return "source_503"
    if "connecttimeout" in msg or "connection timed out" in msg or "timed out" in msg:
        return "timeout"
    if "ssl_error" in msg or "sslv3" in msg or "tls" in msg or "ssl" in msg:
        return "ssl_error"
    if "connection error" in msg or "connectionerror" in msg or "connect" in msg:
        return "connection_error"
    if (
        "resolution error" in msg
        or "resolutionerror" in msg
        or "name or service not known" in msg
        or "getaddrinfo" in msg
    ):
        return "dns_error"
    return "unknown"


def load_radar_history(path: Path | None = None) -> dict:
    """Load radar history JSON. Returns empty dict if file missing."""
    p = path or RADAR_HISTORY_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_radar_history(history: dict, path: Path | None = None) -> None:
    """Save radar history JSON."""
    p = path or RADAR_HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_radar_probe(history: dict, probe_date: str, sources: list[dict]) -> dict:
    """Append a probe result to radar history, keeping last 14 days."""
    if "probes" not in history:
        history["probes"] = []

    history["probes"].append(
        {
            "probe_date": probe_date,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
        }
    )

    # Keep only last 14 days
    cutoff = len(history["probes"]) - 14
    if cutoff > 0:
        history["probes"] = history["probes"][cutoff:]

    return history


def load_registry(path: Path | None = None) -> dict:
    """Load sources registry YAML. Defaults to REGISTRY_PATH."""
    import yaml

    p = path or REGISTRY_PATH
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Registry YAML at {p} must contain a top-level mapping.")
    return data


def save_registry(path: Path | None, registry: dict) -> None:
    """Save registry YAML. Defaults to REGISTRY_PATH."""
    import yaml

    p = path or REGISTRY_PATH
    with p.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(registry, fh, sort_keys=False, allow_unicode=True)


# ── Utility generiche ──────────────────────────────────────────────────────────


def safe_str(v: object) -> str | None:
    """Convert a value to string, handling pandas NaN and None."""
    import math

    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or v != v):
        return None
    return str(v)


def get_red_source_ids(radar_path: Path | None = None) -> list[str]:
    """Read radar_summary.json and return list of RED source IDs.

    Returns empty list if file is missing or unreadable.
    """
    path = radar_path or RADAR_SUMMARY_PATH
    if not path.exists():
        return []
    try:
        radar = json.loads(path.read_text(encoding="utf-8"))
        return [s["id"] for s in radar.get("sources", []) if s.get("status") == "RED"]
    except Exception:
        return []


# ── Join key patterns (condivisi tra source_check_analyze e joinability_scan) ──
# Ogni entry: (chiave_semantica, regex, descrizione)

JOIN_KEY_PATTERNS: list[tuple[str, str, str]] = [
    (
        "istat_comune",
        r"(?i)(codice_istat_comune|codice_comune_istat|^codice_comune$|^pro_com$|^comune$)",
        "Codice ISTAT comune (8 digit alfanumerico)",
    ),
    (
        "istat_regione",
        r"(?i)(codice_istat_regione|^codice_regione$|^codreg$|regione_istat_cod|^cod_reg$|^regione$)",
        "Codice ISTAT regione",
    ),
    (
        "anno",
        r"(?i)^(anno(_|$)|anno_di_imposta$|anno_scolastico$|annoscolastico$|anno_riferimento$|"
        r"anno_presentazione$|esercizio_finanziario$)",
        "Anno / esercizio",
    ),
    (
        "provincia",
        r"(?i)(sigla_provincia|^provincia(_|$)|codice_provincia|sigla_prov|^prov$|^cod_prov$)",
        "Provincia (sigla o codice)",
    ),
    (
        "codice_catastale",
        r"(?i)(codice_catastale|cod_catastale|catastale)",
        "Codice catastale comune",
    ),
    (
        "codice_ente",
        r"(?i)(codice_ente_ipa|^id_ente$|codice_ente_siope|codice_istituzione|"
        r"codice_ente_bdap|codice_ente_ssn|^codice_ente$|^cod_ente$)",
        "Codice ente pubblico (IPA/SIOPE/BDAP/SSN)",
    ),
    (
        "codice_scuola",
        r"(?i)(codice_scuola|codicescuola|codice_meccanografico|^codice_scuola$|^cod_scuola$)",
        "Codice scuola (MIM)",
    ),
    (
        "atc",
        r"(?i)(^atc[1-5]$|^atc$|^atc1$|^atc2$|^atc3$|^atc4$|^atc5$)",
        "Classificazione ATC farmaceutica",
    ),
    (
        "ateco",
        r"(?i)(codice_ateco|^ateco$|sezione_ateco)",
        "Classificazione ATECO attività economica",
    ),
    ("mese", r"(?i)^(mese|month)$", "Mese (1-12)"),
    (
        "cf_ente",
        r"(?i)(codice_fiscale_ente|^cf_ente$|^codice_fiscale$|^cf$|^partita_iva$|^p_iva$)",
        "Codice fiscale / partita IVA ente",
    ),
    (
        "sesso",
        r"(?i)^(sesso|genere|gender)$",
        "Sesso / genere",
    ),
    (
        "eta",
        r"(?i)^(eta|età|eta_|fascia_eta|classe_eta|classe_di_eta|fascia_di_eta$)",
        "Età / fascia età",
    ),
    (
        "cittadinanza",
        r"(?i)(cittadinanza|cittadino|nazionalità|nazionalita)",
        "Cittadinanza / nazionalità",
    ),
    (
        "codice_comune_anagrafe",
        r"(?i)(^codice_comune$|^comune_istat$|^comune_codice$)",
        "Codice comune (generico, forse ISTAT)",
    ),
]

JOIN_KEY_WEIGHTS: dict[str, int] = {
    "istat_comune": 30,
    "istat_regione": 20,
    "anno": 15,
    "provincia": 10,
    "codice_catastale": 15,
    "codice_ente": 10,
    "codice_scuola": 8,
    "atc": 5,
    "ateco": 5,
    "mese": 3,
    "cf_ente": 10,
    "sesso": 3,
    "eta": 3,
    "cittadinanza": 5,
    "codice_comune_anagrafe": 5,
}


def parse_columns(raw: str | None) -> list[str]:
    """Parse a JSON-encoded columns field into a list of column names.

    Handles None, NaN, JSON list, JSON dict (keys as columns), and
    scalar fallback.  Canonical version shared by source_check_analyze
    and joinability_scan.
    """
    import math

    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return []
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [str(raw)]
    if isinstance(parsed, list):
        return [str(c) if not isinstance(c, dict) else str(c.get("name", "")) for c in parsed]
    if isinstance(parsed, dict):
        return list(parsed.keys())
    return [str(parsed)]


def detect_join_keys(
    columns_raw: str | None, columns: list[str] | None = None
) -> dict[str, list[str]]:
    """Match column names against join key patterns.

    Args:
        columns_raw: JSON-encoded columns field (list or dict).
        columns: Already-parsed list (avoids double parse).

    Returns:
        Dict {chiave_semantica: [colonne_matched]}.
    """
    import re

    col_names = columns if columns is not None else parse_columns(columns_raw)
    if not col_names:
        return {}
    found: dict[str, list[str]] = {}
    for key_name, pattern, _desc in JOIN_KEY_PATTERNS:
        matched = [c for c in col_names if re.search(pattern, c.strip())]
        if matched:
            found[key_name] = matched
    return found


def compute_joinability_score(found_keys: dict[str, list[str]]) -> float:
    """Score 0-100 based on found join keys.

    Uses JOIN_KEY_WEIGHTS.  Does not include catalog cross-reference
    (that is added by joinability_scan.py).
    """
    if not found_keys:
        return 0.0
    score = sum(JOIN_KEY_WEIGHTS.get(k, 5) for k in found_keys)
    if len(found_keys) >= 3:
        score += 10
    elif len(found_keys) >= 2:
        score += 5
    return min(score, 100)
