"""Tests for catalog_diff.py — generate_diff."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from catalog_diff import generate_diff


def _report(*sources: tuple) -> dict:
    """Build a minimal report dict from (id, status, rows?, error?) tuples."""
    out: dict = {"captured_at": "2026-04-16T00:00:00+00:00", "sources": {}}
    for item in sources:
        sid, status = item[0], item[1]
        rows = item[2] if len(item) > 2 else None
        err = item[3] if len(item) > 3 else None
        entry: dict = {"status": status, "protocol": "ckan"}
        if rows is not None:
            entry["rows"] = rows
        if err:
            entry["error"] = err
        out["sources"][sid] = entry
    return out





def test_regression_ok_to_error():
    old = _report(("alpha", "ok", 100))
    new = _report(("alpha", "error", 0, "timeout"))
    diff = generate_diff(old, new)
    assert "Regressioni" in diff
    assert "alpha" in diff
    assert "timeout" in diff


def test_recovery_error_to_ok():
    old = _report(("alpha", "error", 0, "WAF"))
    new = _report(("alpha", "ok", 50))
    diff = generate_diff(old, new)
    assert "Recovery" in diff
    assert "alpha" in diff
    assert "Regressioni" not in diff


def test_persistent_error_always_reported():
    old = _report(("alpha", "error", 0, "timeout"))
    new = _report(("alpha", "error", 0, "timeout"))
    diff = generate_diff(old, new)
    assert "Errori persistenti" in diff
    assert "alpha" in diff


def test_persistent_error_changed_message_flagged():
    old = _report(("alpha", "error", 0, "timeout"))
    new = _report(("alpha", "error", 0, "WAF 403"))
    diff = generate_diff(old, new)
    assert "messaggio cambiato" in diff


def test_added_and_removed():
    old = _report(("alpha", "ok", 100))
    new = _report(("beta", "ok", 50))
    diff = generate_diff(old, new)
    assert "Nuove fonti" in diff
    assert "beta" in diff
    assert "rimosse" in diff
    assert "alpha" in diff


def test_row_count_change():
    old = _report(("alpha", "ok", 100))
    new = _report(("alpha", "ok", 120))
    diff = generate_diff(old, new)
    assert "Variazione numero item" in diff
    assert "+20" in diff


def test_recovery_not_in_changed_table():
    """Recovery must not appear in 'Variazione numero item'."""
    old = _report(("alpha", "error", 0, "WAF"))
    new = _report(("alpha", "ok", 50))
    diff = generate_diff(old, new)
    assert "Variazione numero item" not in diff
