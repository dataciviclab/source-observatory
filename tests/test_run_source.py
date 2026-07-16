"""Smoke test per run_source.py.

Verifica che lo script parta e gestisca i casi base
(fonte inesistente, --help, fonte valida). Non fa probe reali.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_source.py"), *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )


class TestRunSourceSmoke:
    """Test minimi che lo script non crasha su input base."""

    @pytest.mark.smoke
    def test_help(self):
        """--help deve funzionare."""
        r = _run("--help")
        assert r.returncode == 0
        assert "End-to-end per una fonte" in r.stdout

    @pytest.mark.smoke
    def test_fonte_inesistente(self):
        """Fonte sconosciuta → exit 1."""
        r = _run("fonte_che_non_esiste")
        assert r.returncode == 1
        assert "non trovata" in r.stderr or "non trovata" in r.stdout

    @pytest.mark.smoke
    def test_fonte_noop(self):
        """Fonte valida con tutti i --no-* deve fare zero probe e uscire con 0."""
        r = _run("anac", "--no-radar", "--no-inventory", "--no-sourcecheck")
        assert r.returncode == 0
        assert "anac" in r.stdout
        assert "Fine" in r.stdout

    @pytest.mark.smoke
    def test_markdown(self):
        """--markdown produce report senza probe e contiene ## Report fonte:."""
        r = _run("anac", "--no-radar", "--no-inventory", "--no-sourcecheck", "--markdown")
        assert r.returncode == 0
        assert "## Report fonte: anac" in r.stdout
        assert "Protocollo" in r.stdout

    @pytest.mark.smoke
    def test_report_flag(self, tmp_path):
        """--report deve salvare JSON senza fare probe."""
        r = _run(
            "anac",
            "--no-radar",
            "--no-inventory",
            "--no-sourcecheck",
            "--report",
            "--report-dir",
            str(tmp_path),
        )
        assert r.returncode == 0
        assert "Report JSON salvato" in r.stdout

        report_file = tmp_path / "source_report_anac.json"
        assert report_file.exists()
        import json

        data = json.loads(report_file.read_text())
        assert data["source_id"] == "anac"
        assert data["report_version"] == 1
        assert "identity" in data
        assert "operational_verdict" in data
        assert data["operational_verdict"]["score"] == "stable"
        assert "all_green" in data["operational_verdict"]["triggers"]
