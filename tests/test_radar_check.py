"""Test per radar_check.py."""
from __future__ import annotations

import json

import radar_check


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_payload: dict | None = None,
        content_type: str = "application/json",
        url: str = "https://example.test/api/3/action/status",
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_payload = json_payload
        self._content_type = content_type
        self.url = url
        self.headers = headers or {
            "content-type": content_type,
        }

    def json(self) -> dict:
        if self._json_payload is None:
            raise json.JSONDecodeError("Expecting value", "doc", 0)
        return self._json_payload

    def raise_for_status(self) -> None:
        pass

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass





def test_probe_url_success(monkeypatch) -> None:
    def fake_get(*args, **kwargs):
        return FakeResponse(
            status_code=200,
            json_payload={"success": True, "result": []},
        )

    monkeypatch.setattr(radar_check.requests, "get", fake_get)
    result = radar_check.probe_url("https://demo.test/api/3/action/package_list")
    assert result.status == "GREEN"
    assert result.http_code == "200"
    assert result.ssl_fallback_used is False


def test_probe_url_timeout(monkeypatch) -> None:
    import requests as real_requests

    def fake_get(*args, **kwargs):
        raise real_requests.exceptions.Timeout("Connection timed out")

    monkeypatch.setattr(radar_check.requests, "get", fake_get)
    result = radar_check.probe_url("https://slow.test/api/3/action")
    assert result.status == "YELLOW"
    assert "Timeout" in (result.note or "")


def test_probe_url_connection_error(monkeypatch) -> None:
    import requests as real_requests

    def fake_get(*args, **kwargs):
        raise real_requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr(radar_check.requests, "get", fake_get)
    result = radar_check.probe_url("https://dead.test/api/3/action")
    assert result.status == "RED"
    assert "Connection error" in (result.note or "")


def test_probe_url_ssl_fallback(monkeypatch) -> None:
    import requests as real_requests

    call_count = {"n": 0}

    def fake_get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise real_requests.exceptions.SSLError("SSL certificate verify failed")
        return FakeResponse(
            status_code=200,
            json_payload={"success": True},
        )

    monkeypatch.setattr(radar_check.requests, "get", fake_get)
    # Disable actual urllib3 warning suppression for test safety
    monkeypatch.setattr(
        radar_check.requests.packages.urllib3,
        "disable_warnings",
        lambda *args, **kwargs: None,
    )

    result = radar_check._probe_once("https://ssl-broken.test/api/3/action")
    assert result.ssl_fallback_used is True
    assert "SSL verify failed" in (result.note or "")


def test_validate_ckan_non_json_is_yellow() -> None:
    """200 con HTML/WAF deve essere YELLOW, non GREEN — caso ANAC reale."""
    response = FakeResponse(status_code=200, content_type="text/html", json_payload=None,
                            headers={"content-type": "text/html"})
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/api/3/action/package_list", response
    )
    assert status == "YELLOW"
    assert "non-JSON" in (note or "")


def test_validate_ckan_missing_success_is_yellow() -> None:
    """200 con JSON valido ma senza campo success deve essere YELLOW."""
    response = FakeResponse(status_code=200, json_payload={"result": []})
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/api/3/action/package_list", response
    )
    assert status == "YELLOW"
    assert "missing" in (note or "").lower()


def test_validate_ckan_invalid_json_is_yellow() -> None:
    """200 con body non parsabile deve essere YELLOW."""
    response = FakeResponse(status_code=200, json_payload=None)
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/api/3/action/package_list", response
    )
    assert status == "YELLOW"
    assert "invalid JSON" in (note or "")


def test_build_status_report_smoke() -> None:
    """Contratto minimo del formato pubblico STATUS.md letto da agenti."""
    registry = {
        "demo_ckan": {"base_url": "https://demo.test/api/3/action/package_list",
                      "source_kind": "catalog", "protocol": "ckan", "observation_mode": "catalog-watch"},
        "istat_sdmx": {"base_url": "https://sdmx.istat.it/rest/", "source_kind": "catalog",
                       "protocol": "sdmx", "observation_mode": "radar-only"},
    }
    results = {
        "demo_ckan": radar_check.ProbeResult(status="GREEN", http_code="200", content_type="application/json"),
        "istat_sdmx": radar_check.ProbeResult(status="YELLOW", http_code="503", note="retry esaurito"),
    }
    report = radar_check.build_status_report(registry, results, "2026-04-17")
    assert "# Stato Radar" in report
    assert "Fonti controllate: 2" in report
    assert "GREEN: 1" in report
    assert "YELLOW: 1" in report
