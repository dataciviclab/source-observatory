"""Conftest per source-observatory.

Aggiunge ``scripts/`` e ``so_mcp/`` a ``sys.path`` in modo che i test
possano importare i moduli senza boilerplate.

Fornisce anche fixture condivise per mock HTTP e artifact locali.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Aggiungi percorsi di import prima di qualsiasi test
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_SO_MCP_DIR = Path(__file__).resolve().parent.parent / "so_mcp"

for _p in (_SCRIPTS_DIR, _SO_MCP_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ------------------------------------------------------------------
# Fixture: artifact backend locale (default per tutti i test)
# ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_local_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tutti i test SO usano artifact backend locale per default."""
    monkeypatch.setenv("SO_ARTIFACT_BACKEND", "local")


# ------------------------------------------------------------------
# Fixture: FakeHttpClient (da lab_connectors.testing)
# ------------------------------------------------------------------


@pytest.fixture
def fake_http() -> Any:
    """Fixture che restituisce un ``FakeHttpClient`` pulito.

    Ogni test riceve un'istanza nuova con ``responses`` e ``requests``
    vuoti.  È un alias per ``FakeHttpClient()`` importato da
    ``lab_connectors.testing``.

    Usage::

        def test_something(fake_http):
            from lab_connectors.http import HttpResult
            from lab_connectors.testing import fake_response

            fake_http.responses["https://example.test/data"] = HttpResult(
                response=fake_response(200, "ok"), err=None,
            )
            result = fake_http.get("https://example.test/data")
            assert result.is_ok
    """
    from lab_connectors.testing import FakeHttpClient

    return FakeHttpClient()
