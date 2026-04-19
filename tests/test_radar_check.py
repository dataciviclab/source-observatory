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


def test_classify_response_green() -> None:
    assert radar_check.classify_response(200) == "GREEN"
    assert radar_check.classify_response(201) == "GREEN"
    assert radar_check.classify_response(301) == "GREEN"
    assert radar_check.classify_response(302) == "GREEN"


def test_classify_response_yellow() -> None:
    assert radar_check.classify_response(400) == "YELLOW"
    assert radar_check.classify_response(404) == "YELLOW"
    assert radar_check.classify_response(403) == "YELLOW"


def test_classify_response_red() -> None:
    assert radar_check.classify_response(500) == "RED"
    assert radar_check.classify_response(502) == "RED"
    assert radar_check.classify_response(503) == "RED"


def test_validate_ckan_action_response_ok() -> None:
    response = FakeResponse(
        status_code=200,
        json_payload={"success": True, "result": []},
    )
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/api/3/action/package_list", response
    )
    assert status == "GREEN"
    assert note is None


def test_validate_ckan_action_response_missing_success() -> None:
    response = FakeResponse(
        status_code=200,
        json_payload={"result": []},
    )
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/api/3/action/package_list", response
    )
    assert status == "YELLOW"
    assert "missing" in (note or "").lower()


def test_validate_ckan_action_response_non_json() -> None:
    response = FakeResponse(
        status_code=200,
        content_type="text/html",
        json_payload=None,
        headers={"content-type": "text/html"},
    )
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/api/3/action/package_list", response
    )
    assert status == "YELLOW"
    assert "non-JSON" in (note or "")


def test_validate_ckan_action_response_invalid_json() -> None:
    response = FakeResponse(status_code=200, json_payload=None)
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/api/3/action/package_list", response
    )
    assert status == "YELLOW"
    assert "invalid JSON" in (note or "")


def test_validate_ckan_action_response_non_ckan_url() -> None:
    response = FakeResponse(status_code=200, content_type="text/html")
    status, note = radar_check.validate_ckan_action_response(
        "https://example.test/", response
    )
    # Non-CKAN URL should just be classified by status code
    assert status == "GREEN"
    assert note is None


def test_is_sdmx_url() -> None:
    assert radar_check._is_sdmx_url("https://example.test/rest/dataflow") is True
    assert radar_check._is_sdmx_url("https://example.test/SDMXWS/data") is True
    assert radar_check._is_sdmx_url("https://example.test/sdmx/v1/data") is True
    assert radar_check._is_sdmx_url("https://example.test/api/3/action") is False
    assert radar_check._is_sdmx_url("https://example.test/datasets") is False


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


def test_build_status_report_basic() -> None:
    registry = {
        "demo_ckan": {
            "base_url": "https://demo.test/api/3/action/package_list",
            "source_kind": "catalog",
            "protocol": "ckan",
            "observation_mode": "catalog-watch",
        },
        "istat_sdmx": {
            "base_url": "https://sdmx.istat.it/rest/",
            "source_kind": "catalog",
            "protocol": "sdmx",
            "observation_mode": "radar-only",
        },
    }
    results = {
        "demo_ckan": radar_check.ProbeResult(
            status="GREEN", http_code="200", content_type="application/json"
        ),
        "istat_sdmx": radar_check.ProbeResult(
            status="YELLOW", http_code="503", note="SDMX retry esaurito"
        ),
    }

    report = radar_check.build_status_report(registry, results, "2026-04-11")

    assert "# Stato Radar" in report
    assert "Ultimo run: 2026-04-11" in report
    assert "Fonti controllate: 2" in report
    assert "GREEN: 1" in report
    assert "YELLOW: 1" in report
    assert "RED: 0" in report
    assert "| demo_ckan |" in report
    assert "| istat_sdmx |" in report
    assert "## Note" in report
    assert "istat_sdmx" in report


def test_build_radar_summary_schema() -> None:
    """Test che build_radar_summary produce un JSON consumabile da ACB."""
    registry = {
        "demo_ckan": {
            "base_url": "https://demo.test/api/3/action/package_list",
            "source_kind": "catalog",
            "protocol": "ckan",
            "observation_mode": "catalog-watch",
            "datasets_in_use": ["dataset1", "dataset2"],
        },
        "istat_sdmx": {
            "base_url": "https://sdmx.istat.it/rest/",
            "source_kind": "catalog",
            "protocol": "sdmx",
            "observation_mode": "radar-only",
            "datasets_in_use": [],
        },
    }
    results = {
        "demo_ckan": radar_check.ProbeResult(
            status="GREEN", http_code="200", content_type="application/json"
        ),
        "istat_sdmx": radar_check.ProbeResult(
            status="YELLOW", http_code="-", note="Timeout"
        ),
    }

    summary = radar_check.build_radar_summary(registry, results, "2026-04-18")

    # Verifica struttura top-level
    assert "generated_at" in summary
    assert "probe_date" in summary
    assert "sources_total" in summary
    assert "status_counts" in summary
    assert "sources" in summary

    # Verifica conteggi
    assert summary["probe_date"] == "2026-04-18"
    assert summary["sources_total"] == 2
    assert summary["status_counts"]["GREEN"] == 1
    assert summary["status_counts"]["YELLOW"] == 1
    assert summary["status_counts"]["RED"] == 0

    # Verifica entry fonte
    sources_by_id = {s["id"]: s for s in summary["sources"]}
    assert "demo_ckan" in sources_by_id
    assert "istat_sdmx" in sources_by_id

    demo = sources_by_id["demo_ckan"]
    assert demo["status"] == "GREEN"
    assert demo["protocol"] == "ckan"
    assert demo["observation_mode"] == "catalog-watch"
    assert demo["http_code"] == "200"
    assert demo["last_check"] == "2026-04-18"
    assert demo["datasets_in_use"] == ["dataset1", "dataset2"]

    istat = sources_by_id["istat_sdmx"]
    assert istat["status"] == "YELLOW"
    assert istat["http_code"] == "-"
    assert istat["datasets_in_use"] == []

    # Verifica JSON-serializable
    json_str = json.dumps(summary)
    assert isinstance(json_str, str)
    reparsed = json.loads(json_str)
    assert reparsed == summary
