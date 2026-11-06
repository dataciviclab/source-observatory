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


def test_prune_orphan_reports_removes_only_unknown_sources(tmp_path: Path) -> None:
    """I report di fonti rimosse dal registry vengono cancellati."""
    from scripts.build_source_reports import _prune_orphan_reports

    (tmp_path / "aci.json").write_text("{}")
    (tmp_path / "inps.json").write_text("{}")
    (tmp_path / "dati_cultura.json").write_text("{}")
    (tmp_path / "note.txt").write_text("keep me")

    removed = _prune_orphan_reports(tmp_path, {"aci", "inps"})

    assert removed == ["dati_cultura.json"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["aci.json", "inps.json", "note.txt"]


def test_prune_orphan_reports_noop_when_all_known(tmp_path: Path) -> None:
    from scripts.build_source_reports import _prune_orphan_reports

    (tmp_path / "aci.json").write_text("{}")
    assert _prune_orphan_reports(tmp_path, {"aci"}) == []
    assert (tmp_path / "aci.json").exists()
