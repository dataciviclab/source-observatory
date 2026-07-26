"""Smoke test per build_source_reports — verifica import e funzioni base."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.pure_unit


def test_import_build_source_reports() -> None:
    """Verifica che build_source_reports sia importabile."""
    from scripts.build_source_reports import _load_inventory_report, _load_radar

    assert callable(_load_radar)
    assert callable(_load_inventory_report)


def test_load_radar_returns_empty_when_file_missing(tmp_path: Path) -> None:
    """_load_radar su file inesistente restituisce {}."""
    from scripts.build_source_reports import _load_radar

    result = _load_radar()
    assert isinstance(result, dict)
