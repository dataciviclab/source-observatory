#!/usr/bin/env python3
"""
Produce open_data_health_scores.json per ogni fonte monitorata.

Punteggio su 6 assi (0-100) basato su dati gia' disponibili in SO.
Ogni asse e' "computed" (dati reali verificati) o "missing"
(dato non disponibile, escluso dal punteggio). Niente stime.

Avvertenza: i punteggi sono diagnostici, non certificativi. Un punteggio
basso significa "abbiamo pochi dati o segnali di criticita'", non
necessariamente "violazione normativa". Le azioni raccomandate richiedono
verifica umana prima di essere intraprese.

Utilizzo:
    python scripts/build_compliance_scores.py
    python scripts/build_compliance_scores.py --out data/health/open_data_health_scores.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _constants import (
    CATALOG_SIGNALS_PATH,
    CHECK_PARQUET_PATH,
    INVENTORY_PARQUET_PATH,
    OPEN_DATA_HEALTH_SCORES_PATH,
    RADAR_SUMMARY_PATH,
    REGISTRY_PATH,
    load_registry,
)

DEFAULT_RADAR = RADAR_SUMMARY_PATH
DEFAULT_SIGNALS = CATALOG_SIGNALS_PATH
DEFAULT_REGISTRY = REGISTRY_PATH
DEFAULT_INVENTORY = INVENTORY_PARQUET_PATH
DEFAULT_SOURCE_CHECK = CHECK_PARQUET_PATH
DEFAULT_OUT = OPEN_DATA_HEALTH_SCORES_PATH

# Pesi per ogni asse
PESI: dict[str, int] = {
    "formato_aperto": 3,
    "raggiungibilita": 2,
    "licenza_aperta": 1,
    "presenza_datigovit": 2,
    "hvd_compliance": 3,
    "accessibilita_foia": 1,
}

ASSI = {
    "formato_aperto": {"label": "A — Formato aperto", "max": 100},
    "raggiungibilita": {"label": "B — Raggiungibilita'", "max": 100},
    "licenza_aperta": {"label": "C — Licenza aperta", "max": 100},
    "presenza_datigovit": {"label": "D — Presenza dati.gov.it", "max": 100},
    "hvd_compliance": {"label": "E — HVD compliance", "max": 100},
    "accessibilita_foia": {"label": "F — Accessibilita' FOIA", "max": 100},
}


def _load_inventory_format_stats(path: Path) -> dict[str, dict]:
    """Legge inventory parquet e calcola % formato aperto per fonte CKAN.

    Restituisce dict: source_id → {"total": N, "aperti": N, "perc_aperto": 0-100}.
    Per fonti non CKAN o senza dati, il source_id non e' presente.
    """
    if not path.exists():
        return {}

    try:
        import duckdb

        con = duckdb.connect()
        rows = con.execute(
            """
            SELECT source_id,
                   COUNT(*) as total,
                   COUNT(CASE WHEN format IS NOT NULL AND format != '' THEN 1 END) as con_formato,
                   SUM(CASE WHEN LOWER(format) LIKE '%csv%' OR LOWER(format) LIKE '%json%' OR LOWER(format) LIKE '%xml%' THEN 1 ELSE 0 END) as aperti
            FROM '"""
            + str(path)
            + """'
            WHERE protocol = 'ckan'
            GROUP BY source_id
        """
        ).fetchall()
        stats = {}
        for sid, total, con_formato, aperti in rows:
            stats[sid] = {
                "total": int(total),
                "con_formato": int(con_formato),
                "aperti": int(aperti),
                "perc_aperto": round(int(aperti) / int(total) * 100, 1) if int(total) > 0 else 0.0,
                "copertura": round(int(con_formato) / int(total) * 100, 1)
                if int(total) > 0
                else 0.0,
            }
        return stats
    except Exception as exc:
        print(f"⚠️  Inventory parquet non elaborabile: {exc}")
        return {}


def _load_inventory_license_stats(path: Path) -> dict[str, dict]:
    """Legge inventory parquet e classifica licenze e HVD per fonte.

    Restituisce dict: source_id → {"license_open_pct": 0-100, "has_hvd": bool}.
    Se le colonne license_id/hvd_category non esistono ancora nel parquet
    (generato prima di questo PR), torna vuoto senza errori.
    """
    if not path.exists():
        return {}

    try:
        import duckdb

        con = duckdb.connect()
        # Verifica colonne disponibili — backward compat
        schema = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()}
        if "license_id" not in schema:
            return {}
    except Exception:
        return {}

    try:
        con = duckdb.connect()
        rows = con.execute(
            f"""
            SELECT source_id,
                   COUNT(*) as total,
                   SUM(CASE WHEN LOWER(license_id) LIKE '%cc-by%' OR LOWER(license_id) LIKE '%cc-zero%' OR LOWER(license_id) LIKE '%cc0%' OR LOWER(license_id) LIKE '%odbl%' OR LOWER(license_id) LIKE '%iodl%' OR LOWER(license_id) = 'other-open' OR LOWER(license_title) LIKE '%creative commons%' OR LOWER(license_title) LIKE '%iodl%' THEN 1 ELSE 0 END) as licenze_aperte,
                   SUM(CASE WHEN hvd_category IS NOT NULL AND hvd_category != '' THEN 1 ELSE 0 END) as con_hvd
            FROM '{path}'
            WHERE protocol = 'ckan'
            GROUP BY source_id
        """
        ).fetchall()
        stats = {}
        for sid, total, licenze_aperte, con_hvd in rows:
            stats[sid] = {
                "total": int(total),
                "licenze_aperte": int(licenze_aperte),
                "perc_licenza_aperta": round(int(licenze_aperte) / int(total) * 100, 1)
                if int(total) > 0
                else 0.0,
                "has_hvd": int(con_hvd) > 0,
            }
        return stats
    except Exception as exc:
        print(f"⚠️  Inventory licenza non elaborabile: {exc}")
        return {}


def _build_source_check_stats(source_id: str, results: list[dict]) -> dict[str, dict]:
    """Aggrega source-check results in memoria → same shape di _load_source_check_stats.

    Usato da run_source.py per passare dati a build_scores() senza passare dal parquet.
    Esclude item SDMX/SPARQL (probe_applicable=False) — non sono probeabili,
    i loro metadati vengono dall'inventory/enrichment, non dal source-check.
    """
    probeable = [r for r in results if r.get("probe_applicable", True)]
    total = len(probeable)
    reachable = sum(1 for r in probeable if r.get("reachable"))
    circuit_open = sum(1 for r in probeable if r.get("check_notes") == "circuit_open")

    formato_aperto = 0
    formato_chiuso = 0
    formato_ignoto = 0
    for r in probeable:
        fmt = (r.get("resource_format") or "").upper().strip()
        if fmt in ("CSV", "JSON", "XML"):
            formato_aperto += 1
        elif fmt in ("XLSX", "XLS", "PDF", "ZIP"):
            formato_chiuso += 1
        elif not fmt:
            formato_ignoto += 1
        else:
            formato_ignoto += 1  # formati non classificati → ignoto

    return {
        source_id: {
            "total": total,
            "reachable": reachable,
            "circuit_open": circuit_open,
            "formato_aperto": formato_aperto,
            "formato_chiuso": formato_chiuso,
            "formato_ignoto": formato_ignoto,
            "perc_reachable": round(reachable / total * 100, 1) if total > 0 else 0.0,
            "perc_aperto": round(formato_aperto / total * 100, 1) if total > 0 else 0.0,
        }
    }


def _build_inventory_stats(source_id: str, rows: list[dict]) -> dict[str, dict]:
    """Aggrega inventory rows in memoria → same shape di _load_inventory_format_stats.

    Considera solo item CKAN (per allineamento con la versione parquet).
    """
    ckan_rows = [r for r in rows if (r.get("protocol") or "").lower() == "ckan"]
    total = len(ckan_rows)
    if total == 0:
        return {}

    con_formato = 0
    aperti = 0
    for r in ckan_rows:
        fmt = (r.get("format") or "").upper().strip()
        if fmt:
            con_formato += 1
        if fmt in ("CSV", "JSON", "XML"):
            aperti += 1

    return {
        source_id: {
            "total": total,
            "con_formato": con_formato,
            "aperti": aperti,
            "perc_aperto": round(aperti / total * 100, 1) if total > 0 else 0.0,
            "copertura": round(con_formato / total * 100, 1) if total > 0 else 0.0,
        }
    }


def _build_license_stats(source_id: str, rows: list[dict]) -> dict[str, dict]:
    """Aggrega inventory rows in memoria → same shape di _load_inventory_license_stats.

    Stessa logica di licenza_aperta e HVD della versione parquet.
    """
    ckan_rows = [r for r in rows if (r.get("protocol") or "").lower() == "ckan"]
    total = len(ckan_rows)
    if total == 0:
        return {}

    licenze_aperte = 0
    con_hvd = 0
    for r in ckan_rows:
        lid = (r.get("license_id") or "").lower()
        ltitle = (r.get("license_title") or "").lower()
        is_open = (
            "cc-by" in lid
            or "cc-zero" in lid
            or "cc0" in lid
            or "odbl" in lid
            or "iodl" in lid
            or lid == "other-open"
            or "creative commons" in ltitle
            or "iodl" in ltitle
        )
        if is_open:
            licenze_aperte += 1

        hvd = str(r.get("hvd_category") or "").strip()
        if hvd:
            con_hvd += 1

    return {
        source_id: {
            "total": total,
            "licenze_aperte": licenze_aperte,
            "perc_licenza_aperta": round(licenze_aperte / total * 100, 1) if total > 0 else 0.0,
            "has_hvd": con_hvd > 0,
        }
    }


def _load_source_check_stats(path: Path) -> dict[str, dict]:
    """Legge source_check_results.parquet e aggrega per fonte.

    Restituisce dict: source_id → {
        "total": N,
        "reachable": N,
        "circuit_open": N,
        "formato_aperto": N,   # CSV/JSON/XML
        "formato_chiuso": N,   # XLSX/XLS/PDF/ZIP
        "formato_ignoto": N,
        "perc_reachable": 0-100,
        "perc_aperto": 0-100,  # su total (formato_chiuso conta come non aperto)
    }.

    Esclude item SDMX/SPARQL (probe_applicable=False) — non sono probeabili.
    Backward compat: se la colonna probe_applicable non esiste (parquet vecchio),
    include tutti gli item (comportamento precedente).
    """
    if not path.exists():
        return {}

    try:
        import duckdb

        con = duckdb.connect()
        schema = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()}
        has_probe_applicable = "probe_applicable" in schema
        # COALESCE: le righe storiche (pre-colonna) hanno probe_applicable=NULL
        # e vanno trattate come probeabili (legacy).
        probe_filter = (
            "WHERE COALESCE(probe_applicable, true) = true" if has_probe_applicable else ""
        )

        rows = con.execute(
            f"""
            SELECT source_id,
                   COUNT(*) as total,
                   SUM(CASE WHEN reachable THEN 1 ELSE 0 END) as reachable,
                   SUM(CASE WHEN check_notes = 'circuit_open' THEN 1 ELSE 0 END) as circuit_open,
                   SUM(CASE WHEN resource_format IN ('CSV', 'JSON', 'XML') THEN 1 ELSE 0 END) as formato_aperto,
                   SUM(CASE WHEN resource_format IN ('XLSX', 'XLS', 'PDF', 'ZIP') THEN 1 ELSE 0 END) as formato_chiuso,
                   SUM(CASE WHEN resource_format IS NULL OR resource_format = '' THEN 1 ELSE 0 END) as formato_ignoto
            FROM '{path}'
            {probe_filter}
            GROUP BY source_id
        """
        ).fetchall()
        stats = {}
        for sid, total, reachable, copen, fap, fchiuso, fignoto in rows:
            t = int(total)
            stats[sid] = {
                "total": t,
                "reachable": int(reachable),
                "circuit_open": int(copen),
                "formato_aperto": int(fap),
                "formato_chiuso": int(fchiuso),
                "formato_ignoto": int(fignoto),
                "perc_reachable": round(int(reachable) / t * 100, 1) if t > 0 else 0.0,
                "perc_aperto": round(int(fap) / t * 100, 1) if t > 0 else 0.0,
            }
        return stats
    except Exception as exc:
        print(f"⚠️  Source-check parquet non elaborabile: {exc}")
        return {}


def _source_check_affidabile(
    source_id: str,
    protocol: str,
    sc_stats: dict | None,
) -> bool:
    """Il source_check e' affidabile per questa fonte?

    Per SDMX e SPARQL, gli item vengono esclusi dalle stats (probe_applicable=False).
    Se total==0, il source-check non ha probeato nulla di reale — non affidabile.

    Per CKAN, HTML, REST, AEM il source_check funziona bene.
    """
    if not sc_stats or source_id not in sc_stats:
        return False
    sc = sc_stats[source_id]
    # Per SDMX/SPARQL: se total==0 (tutti gli item esclusi da probe_applicable),
    # o se nessun item probeabile ha prodotto dati, il source-check non è affidabile.
    if protocol in ("sdmx", "sparql"):
        if sc.get("total", 0) == 0:
            return False
        if sc["reachable"] == 0 and sc["circuit_open"] == 0:
            return False
        return True
    # Per CKAN/HTML/REST: il source-check è affidabile se ha prodotto dati
    return True


def _formato_score(
    protocol: str,
    signals: list[dict],
    inventory_stats: dict | None = None,
    source_id: str = "",
    source_check_stats: dict | None = None,
) -> tuple[float, str]:
    """A — Formato aperto.

    Priorità: source_check (formato reale) > inventory (metadato) > segnali > protocollo.
    """
    # ── 1. Source-check: formato reale da probe HTTP ─────────────────
    if (
        source_check_stats
        and source_id in source_check_stats
        and _source_check_affidabile(source_id, protocol, source_check_stats)
    ):
        sc = source_check_stats[source_id]
        perc_aperto = sc["perc_aperto"]
        perc_reachable = sc["perc_reachable"]

        # Se tutti i formati sono ignoti, source_check non ha probeato il
        # formato — salta a inventory/protocollo
        if sc.get("total", 0) > 0 and sc.get("formato_ignoto", 0) == sc.get("total", 0):
            pass  # casca a inventory
        else:
            # Penalità forte se la maggior parte dei file e' irraggiungibile
            if perc_reachable < 30.0:
                return (10.0, "computed")
            if perc_reachable < 50.0:
                return (15.0, "computed")

            # Formato reale dei file raggiungibili
            if perc_aperto >= 95.0:
                return (90.0, "computed")
            elif perc_aperto >= 80.0:
                return (75.0, "computed")
            elif perc_aperto >= 50.0:
                return (55.0, "computed")
            elif perc_aperto >= 20.0:
                return (35.0, "computed")
            elif perc_aperto > 0:
                # Qualche formato aperto, ma pochissimo
                return (20.0, "computed")
            else:
                # Zero formati aperti — tutto chiuso (XLSX/PDF/ZIP)
                return (5.0, "computed")

    # ── 2. Inventory CKAN (metadati) ──────────────────────────────────
    if inventory_stats and source_id in inventory_stats:
        stats = inventory_stats[source_id]
        perc = stats["perc_aperto"]
        fonte = "computed"
        if perc >= 95.0:
            return (90.0, fonte)
        elif perc >= 80.0:
            return (75.0, fonte)
        elif perc >= 50.0:
            return (55.0, fonte)
        elif perc >= 20.0:
            return (35.0, fonte)
        else:
            return (20.0, fonte)

    # ── 3. Segnali HTML (csv_magnet) ──────────────────────────────────
    for sig in signals:
        detail = sig.get("detail", "")
        if "CSV" in detail and ("JSON" in detail or "XML" in detail):
            return (80.0, "computed")
        if "CSV" in detail:
            return (75.0, "computed")

    # ── 4. Nessun dato — asse non conteggiato ──────────────────────
    return (0.0, "missing")


def _raggiungibilita_score(
    radar_entry: dict | None,
    source_check_stats: dict | None = None,
    source_id: str = "",
    protocol: str = "",
) -> tuple[float, str]:
    """B — Raggiungibilita'. Combina radar (portale) e source_check (file).

    Source_check ha priorità: se i file non sono raggiungibili, il portale
    che risponde HTTP 200 e' irrilevante.
    """
    # ── 1. Source-check: file-level reachability ──────────────────────────
    if (
        source_check_stats
        and source_id in source_check_stats
        and _source_check_affidabile(source_id, protocol, source_check_stats)
    ):
        sc = source_check_stats[source_id]
        perc_reachable = sc["perc_reachable"]
        if perc_reachable < 20.0:
            return (5.0, "computed")
        elif perc_reachable < 40.0:
            return (15.0, "computed")
        elif perc_reachable < 60.0:
            return (30.0, "computed")
        elif perc_reachable < 80.0:
            return (50.0, "computed")

    # ── 2. Radar: portale reachability ──────────────────────────────────
    if radar_entry is None:
        return (0.0, "missing")

    status = radar_entry.get("status", "GREEN")
    note = radar_entry.get("note") or ""
    streak = radar_entry.get("red_streak", 0)

    if status == "GREEN":
        if radar_entry and radar_entry.get("ssl_issue"):
            return (55.0, "computed")
        if "SSL" in note or "ssl" in note.lower():
            return (55.0, "computed")
        return (70.0, "computed")
    elif status == "YELLOW":
        return (30.0, "computed")
    elif status == "RED":
        if isinstance(streak, (int, float)) and streak >= 5:
            return (5.0, "computed")
        elif isinstance(streak, (int, float)) and streak >= 2:
            return (15.0, "computed")
        return (20.0, "computed")

    return (0.0, "missing")


def _licenza_score(
    protocol: str,
    license_stats: dict | None = None,
    source_id: str = "",
) -> tuple[float, str]:
    """C — Licenza aperta. Computed da inventory se disponibile."""
    if license_stats and source_id in license_stats:
        stats = license_stats[source_id]
        perc = stats["perc_licenza_aperta"]
        if perc >= 90.0:
            return (85.0, "computed")
        elif perc >= 50.0:
            return (60.0, "computed")
        elif perc > 0:
            return (40.0, "computed")
        else:
            return (0.0, "missing")
    return (0.0, "missing")


def _datigovit_score(source_info: dict) -> tuple[float, str]:
    """D — Presenza su dati.gov.it.

    Computed: se la base_url contiene dati.gov.it (o dati.consip.it,
    bdap-opendata.rgs.mef.gov.it e altri portali aggregatori noti).
    Estimated: altrimenti.
    """
    base_url = (source_info.get("base_url") or "").lower()
    # Euristica: se la base_url contiene pattern tipici di un portale
    # aggregatore CKAN (dati.gov.it, API action endpoint), la fonte
    # e' probabilmente catalogata su un aggregatore nazionale/regionale.
    # Copre automaticamente nuovi aggregatori senza lista.
    if "dati.gov.it" in base_url:
        return (80.0, "computed")
    if "/api/3/action/" in base_url or "/api/action/" in base_url:
        return (80.0, "computed")
    if "/odapi/" in base_url:
        return (80.0, "computed")
    return (0.0, "missing")


def _hvd_score(
    license_stats: dict | None = None,
    source_id: str = "",
) -> tuple[float, str]:
    """E — HVD compliance. Computed da inventory se disponibile."""
    if license_stats and source_id in license_stats:
        if license_stats[source_id]["has_hvd"]:
            return (80.0, "computed")
        # Sappiamo che non ha HVD (inventory ha la colonna, e' vuota)
        return (50.0, "computed")
    return (50.0, "missing")


def _foia_access_score() -> tuple[float, str]:
    """F — Accessibilita' FOIA. Dipende da anagrafica in data-advocacy."""
    return (50.0, "missing")


def _flag_urgenza(
    source_id: str,
    source_check_stats: dict | None = None,
    radar_entry: dict | None = None,
) -> list[str]:
    """Calcola flag di urgenza per una fonte.

    I flag non modificano lo score ma possono overrideare l'azione raccomandata.
    """
    flags: list[str] = []

    # circuit_open_massivo: >50% URL irraggiungibili
    if source_check_stats and source_id in source_check_stats:
        sc = source_check_stats[source_id]
        if sc["total"] > 0 and (sc["circuit_open"] / sc["total"]) > 0.5:
            flags.append("circuit_open_massivo")

        # formato_chiuso_completo: 0% formato_aperto
        if sc["total"] > 0 and sc["formato_aperto"] == 0 and sc["formato_chiuso"] > 0:
            flags.append("formato_chiuso_completo")

    # portale_irraggiungibile: radar RED streak >= 3
    if radar_entry:
        streak = radar_entry.get("red_streak", 0)
        if isinstance(streak, (int, float)) and streak >= 3:
            flags.append("portale_irraggiungibile")

    return flags


def build_scores(
    registry: dict,
    radar_sources: list[dict],
    signals_data: dict | None,
    inventory_stats: dict | None = None,
    license_stats: dict | None = None,
    source_check_stats: dict | None = None,
) -> dict:
    """Calcola health score per ogni fonte nel registry."""
    radar_by_id: dict[str, dict] = {s["id"]: s for s in radar_sources}

    signals_by_source: dict[str, list[dict]] = {}
    if signals_data:
        for sig in signals_data.get("signals", []):
            src = sig.get("source", "")
            signals_by_source.setdefault(src, []).append(sig)

    scores_list = []

    for source_id, info in registry.items():
        if not isinstance(info, dict):
            continue

        protocol = info.get("protocol", "unknown")
        radar_entry = radar_by_id.get(source_id)
        signals = signals_by_source.get(source_id, [])

        formato, f_src = _formato_score(
            protocol, signals, inventory_stats, source_id, source_check_stats
        )
        raggiung, r_src = _raggiungibilita_score(
            radar_entry, source_check_stats, source_id, protocol
        )
        lic, l_src = _licenza_score(protocol, license_stats, source_id)
        dgov, d_src = _datigovit_score(info)
        hvd, h_src = _hvd_score(license_stats, source_id)
        foia, fo_src = _foia_access_score()

        # Punteggio ponderato — assi "missing" esclusi dal denominatore
        assi_info = [
            (formato, f_src, "formato_aperto"),
            (raggiung, r_src, "raggiungibilita"),
            (lic, l_src, "licenza_aperta"),
            (dgov, d_src, "presenza_datigovit"),
            (hvd, h_src, "hvd_compliance"),
            (foia, fo_src, "accessibilita_foia"),
        ]
        numeratore = 0.0
        denominatore = 0
        for val, src, key in assi_info:
            if src != "missing":
                numeratore += val * PESI[key]
                denominatore += PESI[key]

        totale = round(numeratore / denominatore, 1) if denominatore > 0 else 0.0

        # Livello dal minimo degli assi computed (missing esclusi).
        _ORDINE_LIVELLI = {"buono": 0, "medio": 1, "debole": 2, "carente": 3}

        def _livello_asse(score: float) -> str:
            if score >= 80:
                return "buono"
            elif score >= 55:
                return "medio"
            elif score >= 25:
                return "debole"
            return "carente"

        livelli_assi: list[str] = []
        for val, src, _key in assi_info:
            if src == "missing":
                continue
            livelli_assi.append(_livello_asse(val))

        livello = (
            max(livelli_assi, key=lambda x: _ORDINE_LIVELLI.get(x, 0)) if livelli_assi else "medio"
        )

        # Flag urgenza
        flags = _flag_urgenza(source_id, source_check_stats, radar_entry)

        # I flag possono elevare il livello
        if (
            "circuit_open_massivo" in flags
            and _ORDINE_LIVELLI.get(livello, 0) < _ORDINE_LIVELLI["debole"]
        ):
            livello = "debole"
        if (
            "formato_chiuso_completo" in flags
            and _ORDINE_LIVELLI.get(livello, 0) < _ORDINE_LIVELLI["debole"]
        ):
            livello = "debole"
        if (
            "portale_irraggiungibile" in flags
            and _ORDINE_LIVELLI.get(livello, 0) < _ORDINE_LIVELLI["debole"]
        ):
            livello = "debole"

        # Azione raccomandata
        if livello == "carente":
            azione = "FOIA + verifica DCD"
        elif livello == "debole":
            if "formato_chiuso_completo" in flags:
                azione = "segnalazione DCD (formato chiuso)"
            elif "circuit_open_massivo" in flags:
                azione = "verifica raggiungibilita' (FOIA se persiste)"
            else:
                azione = "verifica umana"
        elif totale < 70 and f_src == "computed" and formato < 40:
            azione = "segnalazione DCD (formato chiuso — verificare)"
        elif totale < 70 and r_src == "computed" and raggiung < 30:
            azione = "verifica raggiungibilita'"
        else:
            azione = "monitoraggio"

        # Quanti assi hanno dati reali (trasparenza per l'utente)
        assi_computed = sum(1 for _, src, _ in assi_info if src == "computed")

        entry = {
            "source_id": source_id,
            "protocol": protocol,
            "totale": totale,
            "livello": livello,
            "azione_raccomandata": azione,
            "flag_urgenza": flags,
            "assi_computed": assi_computed,
            "assi": {
                "formato_aperto": {"score": formato, "fonte": f_src},
                "raggiungibilita": {"score": raggiung, "fonte": r_src},
                "licenza_aperta": {"score": lic, "fonte": l_src},
                "presenza_datigovit": {"score": dgov, "fonte": d_src},
                "hvd_compliance": {"score": hvd, "fonte": h_src},
                "accessibilita_foia": {"score": foia, "fonte": fo_src},
            },
        }
        scores_list.append(entry)

    scores_list.sort(key=lambda x: x["totale"], reverse=True)

    dist = {
        "buono": sum(1 for s in scores_list if s["livello"] == "buono"),
        "medio": sum(1 for s in scores_list if s["livello"] == "medio"),
        "debole": sum(1 for s in scores_list if s["livello"] == "debole"),
        "carente": sum(1 for s in scores_list if s["livello"] == "carente"),
    }

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sources_scored": len(scores_list),
        "distribuzione": dist,
        "scores": scores_list,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Produce open_data_health_scores.json")
    parser.add_argument(
        "--radar",
        default=DEFAULT_RADAR,
        type=Path,
        help="Path a radar_summary.json",
    )
    parser.add_argument(
        "--signals",
        default=DEFAULT_SIGNALS,
        type=Path,
        help="Path a catalog_signals.json",
    )
    parser.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY,
        type=Path,
        help="Path a sources_registry.yaml",
    )
    parser.add_argument(
        "--inventory",
        default=DEFAULT_INVENTORY,
        type=Path,
        help="Path a catalog_inventory_latest.parquet",
    )
    parser.add_argument(
        "--source-check",
        default=DEFAULT_SOURCE_CHECK,
        type=Path,
        help="Path a source_check_results.parquet",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        type=Path,
        help="Path output open_data_health_scores.json",
    )
    args = parser.parse_args()

    registry = load_registry(args.registry)

    radar_sources: list[dict] = []
    if args.radar.exists():
        radar = json.loads(args.radar.read_text(encoding="utf-8"))
        radar_sources = radar.get("sources", [])

    signals_data: dict | None = None
    if args.signals.exists():
        signals_data = json.loads(args.signals.read_text(encoding="utf-8"))

    inventory_stats = _load_inventory_format_stats(args.inventory)
    license_stats = _load_inventory_license_stats(args.inventory)
    source_check_stats = _load_source_check_stats(args.source_check)

    scores = build_scores(
        registry,
        radar_sources,
        signals_data,
        inventory_stats,
        license_stats,
        source_check_stats,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(scores, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    dist = scores["distribuzione"]
    print(f"Health scores salvati in {args.out}")
    print(f"  Fonti: {scores['sources_scored']}")
    print(
        f"  Buono: {dist['buono']}, Medio: {dist['medio']}, "
        f"Debole: {dist['debole']}, Carente: {dist['carente']}"
    )

    critici = [s for s in scores["scores"] if s["livello"] in ("debole", "carente")]
    if critici:
        print(f"\nFonti deboli/carenti ({len(critici)}):")
        for s in critici:
            print(f"  {s['source_id']}: {s['totale']}/100 ({s['azione_raccomandata']})")


if __name__ == "__main__":
    main()
