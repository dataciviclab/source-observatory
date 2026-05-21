"""Tests for build_catalog_signals.py."""
import json
from pathlib import Path

import jsonschema
import pytest
from build_catalog_signals import _classify, build_signals, build_watch_report

_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _report(*sources: tuple) -> dict:
    return {
        "captured_at": "2026-04-17T10:00:00+00:00",
        "sources": {sid: info for sid, info in sources},
    }


def _ok(rows: int = 100, method: str = "package_list", protocol: str = "ckan") -> dict:
    return {"status": "ok", "protocol": protocol, "rows": rows, "method": method}


def _error(msg: str = "timeout", protocol: str = "ckan") -> dict:
    return {"status": "error", "protocol": protocol, "error": msg}


def _non_inv(protocol: str = "ckan") -> dict:
    return {"status": "non_inventariabile", "protocol": protocol, "reason": "WAF attivo."}


# --- stabile ---

def test_stable_no_previous():
    sig = _classify("src", _ok(), None)
    assert sig["signal_type"] == "no signal"
    assert sig["result"] == "stabile"
    assert sig["metric_value"] == 100


def test_stable_same_rows():
    sig = _classify("src", _ok(rows=100), _ok(rows=100))
    assert sig["result"] == "stabile"


# --- inventory change ---

def test_inventory_change_detected():
    sig = _classify("src", _ok(rows=150), _ok(rows=100))
    assert sig["signal_type"] == "inventory change"
    assert sig["metric_value"] == 150
    assert "+50" in sig["detail"]


def test_inventory_change_negative_delta():
    sig = _classify("src", _ok(rows=80), _ok(rows=100))
    assert sig["signal_type"] == "inventory change"
    assert "-20" in sig["detail"]


# --- method mismatch → missing_data ---

def test_method_mismatch_emits_missing_data():
    current = _ok(rows=200, method="package_list")
    prev = _ok(rows=100, method="package_search")
    sig = _classify("src", current, prev)
    assert sig["signal_type"] == "missing_data"
    assert sig["result"] == "missing_data"
    assert "package_search" in sig["detail"]
    assert "package_list" in sig["detail"]


def test_method_mismatch_even_if_rows_same():
    current = _ok(rows=100, method="package_list")
    prev = _ok(rows=100, method="package_search")
    sig = _classify("src", current, prev)
    assert sig["signal_type"] == "missing_data"


def test_no_mismatch_when_prev_method_missing():
    """Se il report precedente non ha method, non bloccare su mismatch."""
    prev = {"status": "ok", "protocol": "ckan", "rows": 100}  # no method field
    sig = _classify("src", _ok(rows=150, method="package_list"), prev)
    assert sig["signal_type"] == "inventory change"


# --- health delegated to radar ---

def test_error_delegated_to_radar_summary():
    sig = _classify("src", _error("connection refused"), _ok())
    assert sig["signal_type"] == "no signal"
    assert sig["result"] == "skipped"
    assert "radar_summary" in sig["detail"]


def test_repeated_error_stays_silent_for_catalog_signals():
    sig = _classify("src", _error("timeout"), _error("timeout"))
    assert sig["signal_type"] == "no signal"
    assert sig["result"] == "skipped"
    assert "radar_summary" in sig["detail"]


def test_recovery_is_not_reported_as_catalog_signal():
    sig = _classify("src", _ok(rows=100), _error("timeout"))
    assert sig["signal_type"] == "no signal"
    assert sig["result"] == "stabile"
    assert sig["metric_value"] == 100


# --- non_inventariabile ---

def test_non_inventariabile_stable_if_never_ok():
    sig = _classify("src", _non_inv(), None)
    assert sig["result"] == "stabile"
    assert sig["signal_type"] == "no signal"


def test_non_inventariabile_regression_if_was_ok():
    sig = _classify("src", _non_inv(), _ok())
    assert sig["signal_type"] == "structural drift"
    assert sig["result"] == "regressione"


# --- html / csv_magnet ---

def _html_csv_magnet(total: int) -> dict:
    return {
        "status": "ok",
        "protocol": "html",
        "source_id": "dati_salute",
        "summary": {
            "type": "csv_magnet",
            "total_links_estimate": total,
            "by_format": {"CSV": 6, "JSON": 2, "XML": 3, "ZIP": 4},
            "prefix_matrix": {"FRM": 3, "C": 6},
            "years_range": [2022, 2026],
            "topics": {"sanita": 1},
        },
    }


def test_html_csv_magnet_high_signal():
    sig = _classify("dati_salute", _html_csv_magnet(286), None)
    assert sig["signal_type"] == "csv_magnet"
    assert sig["result"] == "scan_completed"
    assert sig["metric_value"] == 286
    assert sig["suggested_action"] == "catalog-watch-ready"
    assert "prefix_matrix" in sig
    assert "series" in sig


def test_html_csv_magnet_low_signal():
    sig = _classify("dati_salute", _html_csv_magnet(5), None)
    assert sig["signal_type"] == "csv_magnet"
    assert sig["result"] == "scan_completed"
    assert sig["metric_value"] == 5
    assert sig["suggested_action"] == "low signal"


def test_html_csv_magnet_error():
    info = {
        "status": "ok",
        "protocol": "html",
        "source_id": "dati_salute",
        "summary": {"type": "csv_magnet_error", "message": "HTTP 404"},
    }
    sig = _classify("dati_salute", info, None)
    assert sig["signal_type"] == "csv_magnet"
    assert sig["result"] == "error"
    assert sig["suggested_action"] == "verificare raggiungibilità del portale"


def test_html_no_summary_skipped():
    info = {"status": "ok", "protocol": "html", "source_id": "dati_salute"}
    sig = _classify("dati_salute", info, None)
    assert sig["signal_type"] == "no signal"
    assert sig["result"] == "skipped"


# --- build_signals integration ---

def test_build_signals_structure():
    report = _report(("istat", _ok(rows=4212, method="dataflow_count", protocol="sdmx")))
    out = build_signals(report, None)
    assert out["sources_checked"] == 1
    assert out["captured_at"] == report["captured_at"]
    assert len(out["signals"]) == 1


def test_build_signals_method_mismatch_end_to_end():
    current = _report(("anac", _ok(rows=200, method="package_list")))
    previous = _report(("anac", _ok(rows=100, method="package_search")))
    out = build_signals(current, previous)
    assert out["signals"][0]["signal_type"] == "missing_data"


def test_build_signals_suppresses_health_regressions():
    current = _report(("anac", _error("timeout")))
    previous = _report(("anac", _ok(rows=100)))
    out = build_signals(current, previous)
    assert out["signals"][0]["signal_type"] == "no signal"
    assert out["signals"][0]["result"] == "skipped"


# --- build_watch_report ---

def test_watch_report_no_signals():
    signals = {"captured_at": "2026-04-20", "sources_checked": 3, "signals": [
        {"source": "istat", "protocol": "sdmx", "signal_type": "no signal", "result": "stabile", "detail": "ok", "suggested_action": "nessuna"},
    ]}
    report = build_watch_report(signals)
    assert "Catalog Watch Report" in report
    assert "Nessun segnale" in report
    assert "radar_summary" in report


def test_watch_report_with_inventory_change():
    signals = {"captured_at": "2026-04-20", "sources_checked": 2, "signals": [
        {"source": "inps", "protocol": "ckan", "signal_type": "inventory change", "result": "inventory change",
         "detail": "delta +12", "suggested_action": "verificare", "metric_value": 2335},
        {"source": "istat", "protocol": "sdmx", "signal_type": "no signal", "result": "stabile", "detail": "ok", "suggested_action": "nessuna"},
    ]}
    report = build_watch_report(signals)
    assert "inps" in report
    assert "inventory change" in report
    assert "verificare" in report
    assert "2335" in report


def test_signals_json_schema() -> None:
    """Produce un signals realistico e validalo contro lo schema."""
    prev = _report(("inps", _ok(rows=2323)))
    curr = _report(("inps", _ok(rows=2335)))
    result = build_signals(curr, prev, None)
    schema = _load_schema("catalog_signals.schema.json")
    jsonschema.validate(instance=result, schema=schema)


def test_csv_magnet_signal_schema() -> None:
    """Un segnale csv_magnet con topics e years_range deve essere valido."""
    payload = {
        "captured_at": "2026-05-17T10:00:00+00:00",
        "sources_checked": 1,
        "signals": [
            {
                "source": "mim_opendata",
                "protocol": "html",
                "signal_type": "csv_magnet",
                "result": "scan_completed",
                "detail": "1116 link data (CSV 372, JSON 372, XML 372), years 2015-2025",
                "suggested_action": "catalog-watch-ready",
                "prefix_matrix": {"SCUANAGR": 66, "ALUCORSO": 120, "INFANZIA": 192},
                "topics": {"istruzione": 1116},
                "years_range": [2015, 2025],
            }
        ],
    }
    schema = _load_schema("catalog_signals.schema.json")
    jsonschema.validate(instance=payload, schema=schema)
pytestmark = pytest.mark.contract
