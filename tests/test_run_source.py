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
        r = _run("anac", "--no-radar", "--no-inventory", "--no-sourcecheck", "--no-health")
        assert r.returncode == 0
        assert "anac" in r.stdout
        assert "Fine" in r.stdout

    @pytest.mark.smoke
    def test_markdown(self):
        """--markdown produce report senza probe e contiene ## Report fonte:."""
        r = _run(
            "anac", "--no-radar", "--no-inventory", "--no-sourcecheck", "--no-health", "--markdown"
        )
        assert r.returncode == 0
        assert "## Report fonte: anac" in r.stdout
        assert "Protocollo" in r.stdout
