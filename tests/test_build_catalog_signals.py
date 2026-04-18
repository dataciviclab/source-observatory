"""Tests for build_catalog_signals.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_catalog_signals import build_signals, _classify


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


# --- inventory change ---

def test_inventory_change_detected():
    sig = _classify("src", _ok(rows=150), _ok(rows=100))
    assert sig["signal_type"] == "inventory change"
    assert sig["metric_value"] == 150
    assert "+50" in sig["detail"]


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


def test_persistent_regression_changed_message():
    sig = _classify("src", _error("503 Service Unavailable"), _error("timeout"))
    assert sig["result"] == "regressione"
    assert "messaggio cambiato" in sig["detail"]


# --- recovery ---

def test_recovery():
    sig = _classify("src", _ok(rows=100), _error("timeout"))
    assert sig["signal_type"] == "health"
    assert sig["result"] == "recovery"
    assert sig["metric_value"] == 100


def test_non_inventariabile_regression_if_was_ok():
    sig = _classify("src", _non_inv(), _ok())
    assert sig["signal_type"] == "structural drift"
    assert sig["result"] == "regressione"


# --- build_signals integration ---


def test_build_signals_method_mismatch_end_to_end():
    current = _report(("anac", _ok(rows=200, method="package_list")))
    previous = _report(("anac", _ok(rows=100, method="package_search")))
    out = build_signals(current, previous)
    assert out["signals"][0]["signal_type"] == "missing_data"
