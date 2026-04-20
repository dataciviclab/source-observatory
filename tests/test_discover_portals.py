from __future__ import annotations

import discover_portals


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        content_type: str = "application/json",
        payload: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.text = '{"success": true, "result": []}'
        self._payload = payload or {"success": True, "result": []}

    def json(self) -> dict:
        return self._payload


def test_probe_ckan_uses_aggressive_timeout(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_get(url, timeout=None, **_kwargs):
        observed["url"] = url
        observed["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(discover_portals, "observatory_get", fake_get)
    discover_portals._DDG_PATHS.clear()

    url = discover_portals._probe_ckan("https://example.gov.it")

    assert url == "https://example.gov.it/api/3/action/package_list"
    assert observed["timeout"] == discover_portals.PROBE_TIMEOUT_SECONDS


def test_detect_protocol_returns_html_when_probes_fail(monkeypatch) -> None:
    def fake_get(*_args, **_kwargs):
        raise RuntimeError("host unreachable")

    monkeypatch.setattr(discover_portals, "observatory_get", fake_get)
    discover_portals._DDG_PATHS.clear()

    protocol, probe_url = discover_portals.detect_protocol("example.gov.it")

    assert protocol == "html"
    assert probe_url is None
