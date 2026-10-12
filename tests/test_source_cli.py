"""Test per scripts/source_cli.py — comandi singola-fonte."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.source_cli import main


class TestResolveSource:
    @pytest.mark.pure_unit
    def test_pyproject_local(self, tmp_path: Path, monkeypatch, capsys):
        (tmp_path / "pyproject.toml").write_text(
            """
[tool.observatory]
source_id = "demo"
protocol = "ckan"
base_url = "https://ex.it/api/3/action/package_list"
""",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        rc = main(["probe", "demo"])
        out = capsys.readouterr().out
        assert rc in (0, 1)  # GREEN=0, YELLOW/RED=1 — la risoluzione funziona
        assert "demo" in out
        assert "https://ex.it" in out

    @pytest.mark.pure_unit
    def test_not_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        rc = main(["probe", "fonte-inesistente"])
        assert rc == 2
        assert "non trovata" in capsys.readouterr().err


class TestStatus:
    @pytest.mark.pure_unit
    def test_status_runs(self, monkeypatch, capsys):
        # Radar centrale potrebbe non esistere nel test — comunque non deve crashare
        monkeypatch.chdir(Path.cwd())
        rc = main(["status"])
        assert rc == 0


class TestReport:
    @pytest.mark.pure_unit
    def test_report_local_catalog(self, tmp_path: Path, monkeypatch, capsys):
        reg = tmp_path / "registry"
        reg.mkdir()
        (reg / "catalog.json").write_text(
            json.dumps({"source_id": "demo", "health": {"radar_status": "GREEN"}}),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        rc = main(["report", "demo", "--repo-root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "GREEN" in out

    @pytest.mark.pure_unit
    def test_report_not_found(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        rc = main(["report", "fonte-inesistente"])
        assert rc == 2
        assert "Nessun report" in capsys.readouterr().err
