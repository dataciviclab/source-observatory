"""Test della guardia robots.txt per i fetch HTML diretti."""

from __future__ import annotations

import pytest
from lab_connectors.http import HttpResult
from lab_connectors.testing import FakeHttpClient, fake_response

from scripts.collectors.robots import RobotsGuard

pytestmark = pytest.mark.pure_unit


def _guard(fake: FakeHttpClient) -> RobotsGuard:
    return RobotsGuard(client_factory=lambda **kw: fake)


def _robots(status: int, text: str = "") -> HttpResult:
    return HttpResult(response=fake_response(status, text=text), err=None)


def test_allows_when_robots_missing() -> None:
    """robots.txt 404 = nessuna regola → fetch consentito."""
    fake = FakeHttpClient()
    fake.responses["https://example.test/robots.txt"] = _robots(404)
    assert _guard(fake).can_fetch("https://example.test/page") is True


def test_disallows_matching_path() -> None:
    fake = FakeHttpClient()
    fake.responses["https://example.test/robots.txt"] = _robots(
        200,
        "User-agent: *\nDisallow: /privato/\n",
    )
    guard = _guard(fake)
    assert guard.can_fetch("https://example.test/privato/x") is False
    assert guard.can_fetch("https://example.test/pubblico/x") is True


def test_uses_first_matching_user_agent_block() -> None:
    """Il gruppo dedicato al nostro UA vince su quello generico."""
    fake = FakeHttpClient()
    fake.responses["https://example.test/robots.txt"] = _robots(
        200,
        ("User-agent: *\nDisallow: /\n\nUser-agent: DataCivicLab-SourceObservatory\nAllow: /\n"),
    )
    assert _guard(fake).can_fetch("https://example.test/page") is True


def test_cache_per_origin() -> None:
    """Una sola richiesta a robots.txt per origine, anche su più URL."""
    fake = FakeHttpClient()
    fake.responses["https://example.test/robots.txt"] = _robots(404)
    guard = _guard(fake)

    assert guard.can_fetch("https://example.test/a") is True
    assert guard.can_fetch("https://example.test/b") is True
    assert [r[1] for r in fake.requests] == ["https://example.test/robots.txt"]


def test_separate_origins_fetched_separately() -> None:
    fake = FakeHttpClient()
    fake.responses["https://a.test/robots.txt"] = _robots(404)
    fake.responses["https://b.test/robots.txt"] = _robots(404)
    guard = _guard(fake)

    guard.can_fetch("https://a.test/x")
    guard.can_fetch("https://b.test/x")
    assert len(fake.requests) == 2


def test_fail_open_on_network_error() -> None:
    """Robots illeggibile → fetch consentito ma errore tracciato."""

    class _Broken:
        def __init__(self, **kwargs) -> None:
            pass

        def get(self, url: str, **kwargs):
            raise ConnectionError("boom")

    guard = RobotsGuard(client_factory=_Broken)
    assert guard.can_fetch("https://broken.test/page") is True
    assert "https://broken.test" in guard.errors


def test_fail_open_on_5xx() -> None:
    fake = FakeHttpClient()
    fake.responses["https://example.test/robots.txt"] = _robots(503)
    guard = _guard(fake)
    assert guard.can_fetch("https://example.test/page") is True
    assert "https://example.test" in guard.errors


def test_url_without_scheme_is_allowed() -> None:
    guard = RobotsGuard(client_factory=lambda **kw: FakeHttpClient())
    assert guard.can_fetch("/relative/path") is True
