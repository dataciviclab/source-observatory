"""
Test gha/publish_radar_summary.py — rendering radar_summary in markdown.

Rendering puro da JSON a markdown; RADAR_SUMMARY_PATH mockato.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.pure_unit


class _FakePath:
    """Path finto: read_text ritorna il JSON, write_text cattura l'output."""

    def __init__(self, data: dict):
        self._data = data
        self.written: str | None = None

    def read_text(self, encoding: str = "utf-8") -> str:
        return json.dumps(self._data)

    def write_text(self, content: str, encoding: str = "utf-8") -> None:
        self.written = content


def test_publish_basic(monkeypatch, tmp_path):
    """Rendering base: conteggi, fonti, nessun RED persistente."""
    from scripts.gha import publish_radar_summary

    fake = _FakePath(
        {
            "sources_total": 3,
            "status_counts": {"GREEN": 2, "YELLOW": 1},
            "persistent_red": None,
            "sources": [
                {"id": "anac", "status": "GREEN", "http_code": 200, "note": "ok"},
                {"id": "istat", "status": "YELLOW", "http_code": 200, "note": None},
            ],
        }
    )
    monkeypatch.setattr(publish_radar_summary, "RADAR_SUMMARY_PATH", fake)
    monkeypatch.chdir(tmp_path)

    publish_radar_summary.main()

    # l'output e' scritto su radar_summary.md nella cwd (tmp_path)
    written = (tmp_path / "radar_summary.md").read_text(encoding="utf-8")
    assert "Fonti controllate: 3" in written
    assert "GREEN: 2" in written
    assert "YELLOW: 1" in written
    assert "anac" in written
    assert "istat" in written


def test_publish_persistent_red(monkeypatch, tmp_path):
    """RED persistenti → blocco warning nel markdown."""
    from scripts.gha import publish_radar_summary

    fake = _FakePath(
        {
            "sources_total": 1,
            "status_counts": {"RED": 1},
            "persistent_red": 1,
            "sources": [
                {"id": "giu", "status": "RED", "http_code": 0, "note": "timeout", "red_streak": 3},
            ],
        }
    )
    monkeypatch.setattr(publish_radar_summary, "RADAR_SUMMARY_PATH", fake)
    monkeypatch.chdir(tmp_path)

    publish_radar_summary.main()

    written = (tmp_path / "radar_summary.md").read_text(encoding="utf-8")
    assert "[!WARNING]" in written
    assert "fonti RED persistenti" in written
    assert "⚠️" in written  # red_streak >= 2
