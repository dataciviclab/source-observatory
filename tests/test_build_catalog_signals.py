"""Tests for build_catalog_signals.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_catalog_signals import build_signals, build_watch_report, _classify


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
