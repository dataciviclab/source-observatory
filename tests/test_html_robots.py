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


def _guard_with(text: str) -> RobotsGuard:
    fake = FakeHttpClient()
    fake.responses["https://example.test/robots.txt"] = _robots(200, text)
    return _guard(fake)


def test_allow_more_specific_wins_over_disallow_all() -> None:
    """`Disallow: /` + `Allow: /public/` non deve bloccare /public/a."""
    guard = _guard_with("User-agent: *\nDisallow: /\nAllow: /public/\n")
    assert guard.can_fetch("https://example.test/public/a") is True
    assert guard.can_fetch("https://example.test/altro/a") is False


def test_wildcard_in_disallow_matches_path() -> None:
    """`Disallow: /private/*` deve bloccare /private/a."""
    guard = _guard_with("User-agent: *\nDisallow: /private/*\n")
    assert guard.can_fetch("https://example.test/private/a") is False
    assert guard.can_fetch("https://example.test/private") is True


def test_wildcard_suffix_blocks_all_pdfs() -> None:
    """`Disallow: /*.pdf` deve bloccare i PDF."""
    guard = _guard_with("User-agent: *\nDisallow: /*.pdf\n")
    assert guard.can_fetch("https://example.test/doc/file.pdf") is False
    assert guard.can_fetch("https://example.test/doc/file.csv") is True


def test_dollar_anchor_matches_only_exact_end() -> None:
    guard = _guard_with("User-agent: *\nDisallow: /solo-questo$\n")
    assert guard.can_fetch("https://example.test/solo-questo") is False
    assert guard.can_fetch("https://example.test/solo-questo/altro") is True


def test_equal_length_allow_wins_over_disallow() -> None:
    """A parità di specificità RFC 9309 dà ragione ad Allow."""
    guard = _guard_with("User-agent: *\nDisallow: /p\nAllow: /p\n")
    assert guard.can_fetch("https://example.test/p") is True


def test_query_string_partecipa_al_match() -> None:
    guard = _guard_with("User-agent: *\nDisallow: /*?page=2\n")
    assert guard.can_fetch("https://example.test/dati?page=2") is False
    assert guard.can_fetch("https://example.test/dati?page=1") is True
