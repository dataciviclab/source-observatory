"""Test per le primitive di probe del motore (``scripts.engine.probe``).

Stavano in ``tests/test_radar_check.py``: il probe è usato da entrambi i ruoli
(radar centrale + ``health`` del catalog per-repo), quindi ora è una primitiva
del motore e i suoi test vivono con lui.
"""

from __future__ import annotations

import pytest
from lab_connectors.http import HttpFallbackError, HttpResult
from lab_connectors.testing import FakeHttpClient, fake_response

import scripts.engine.probe as probe

pytestmark = pytest.mark.contract


class TestClassify:
    def test_classify_response_green(self) -> None:
        assert probe.classify_response(200) == "GREEN"
        assert probe.classify_response(201) == "GREEN"
        assert probe.classify_response(301) == "GREEN"
        assert probe.classify_response(302) == "GREEN"

    def test_classify_response_yellow(self) -> None:
        assert probe.classify_response(400) == "YELLOW"
        assert probe.classify_response(404) == "YELLOW"
        assert probe.classify_response(403) == "YELLOW"

    def test_classify_response_red(self) -> None:
        assert probe.classify_response(500) == "RED"
        assert probe.classify_response(502) == "RED"
        assert probe.classify_response(503) == "RED"


class TestValidateCkan:
    def test_validate_ckan_action_response_ok(self) -> None:
        response = fake_response(
            200,
            json_data={"success": True, "result": []},
            headers={"content-type": "application/json"},
        )
        status, note = probe.validate_ckan_action_response(
            "https://example.test/api/3/action/package_list", response
        )
        assert status == "GREEN"
        assert note is None

    def test_validate_ckan_action_response_missing_success(self) -> None:
        response = fake_response(
            200, json_data={"result": []}, headers={"content-type": "application/json"}
        )
        status, note = probe.validate_ckan_action_response(
            "https://example.test/api/3/action/package_list", response
        )
        assert status == "YELLOW"
        assert "missing" in (note or "").lower()

    def test_validate_ckan_action_response_non_json(self) -> None:
        response = fake_response(
            200,
            text="<html>",
            headers={"content-type": "text/html"},
        )
        status, note = probe.validate_ckan_action_response(
            "https://example.test/api/3/action/package_list", response
        )
        assert status == "YELLOW"
        assert "non-JSON" in (note or "")


class TestProbe:
    def test_probe_url_success(self, monkeypatch) -> None:
        """Primary request succeeds — ssl_fallback_used=None."""
        fake = FakeHttpClient()
        fake.responses["https://demo.test/api/3/action/package_list"] = HttpResult(
            response=fake_response(
                200,
                json_data={"success": True, "result": []},
                headers={"content-type": "application/json"},
            ),
            err=None,
            ssl_fallback_used=None,
        )
        monkeypatch.setattr(probe, "HttpClient", lambda **kw: fake)
        result = probe.probe_url("https://demo.test/api/3/action/package_list")
        assert result.status == "GREEN"
        assert result.http_code == "200"
        assert result.ssl_fallback_used is False

    def test_probe_url_timeout(self, monkeypatch) -> None:
        """Timeout → YELLOW."""
        import requests as real_requests

        fake = FakeHttpClient()
        fake.responses["https://slow.test/api/3/action"] = HttpResult(
            response=None,
            err=real_requests.exceptions.Timeout("Connection timed out"),
            ssl_fallback_used=False,
        )
        monkeypatch.setattr(probe, "HttpClient", lambda **kw: fake)
        result = probe.probe_url("https://slow.test/api/3/action")
        assert result.status == "YELLOW"
        assert "Timeout" in (result.note or "")

    def test_probe_url_connection_error(self, monkeypatch) -> None:
        """ConnectionError → RED."""
        import requests as real_requests

        fake = FakeHttpClient()
        fake.responses["https://dead.test/api/3/action"] = HttpResult(
            response=None,
            err=real_requests.exceptions.ConnectionError("Connection refused"),
            ssl_fallback_used=False,
        )
        monkeypatch.setattr(probe, "HttpClient", lambda **kw: fake)
        result = probe.probe_url("https://dead.test/api/3/action")
        assert result.status == "RED"
        assert "Connection error" in (result.note or "")

    def test_probe_url_ssl_fallback_success(self, monkeypatch) -> None:
        """SSL error first, fallback succeeds — ssl_fallback_used=True."""
        fake = FakeHttpClient()
        fake.responses["https://ssl-broken.test/api/3/action"] = HttpResult(
            response=fake_response(
                200, json_data={"success": True}, headers={"content-type": "application/json"}
            ),
            err=None,
            ssl_fallback_used=True,
        )
        monkeypatch.setattr(probe, "HttpClient", lambda **kw: fake)
        result = probe._probe_once("https://ssl-broken.test/api/3/action")
        assert result.ssl_fallback_used is True
        assert result.status == "GREEN"

    def test_probe_url_ssl_fallback_double_failure(self, monkeypatch) -> None:
        """SSL error first, fallback also fails — ssl_fallback_used=False in HttpResult.

        But ssl_failure_err is the primary SSLError → ssl_fallback_used=True in ProbeResult.
        """
        import requests as real_requests

        ssl_exc = real_requests.exceptions.SSLError("SSL cert verify failed")
        fallback_exc = real_requests.exceptions.ConnectionError("Connection refused after fallback")
        fake = FakeHttpClient()
        fake.responses["https://ssl-broken.test/api/3/action"] = HttpResult(
            response=None,
            err=HttpFallbackError(primary_error=ssl_exc, fallback_error=fallback_exc),
            ssl_fallback_used=False,
        )
        monkeypatch.setattr(probe, "HttpClient", lambda **kw: fake)
        result = probe._probe_once("https://ssl-broken.test/api/3/action")
        # ssl_failure_err is the primary SSLError → ssl_fallback_used=True in ProbeResult
        assert result.ssl_fallback_used is True
        assert "SSL verify failed" in (result.note or "")

    def test_probe_url_sdmx_uses_allstubs_and_dedicated_timeout(self, monkeypatch) -> None:
        """URL SDMX → fetch con ?detail=allstubs e timeout dedicato (180s).

        Il catalogo SDMX completo (ISTAT) va in timeout con il timeout standard
        (10s): la fetch deve usare detail=allstubs e SDMX_TIMEOUT_SECONDS.
        """
        fake = FakeHttpClient()
        sdmx_url = "https://sdmx.test/dataflow/IT1"
        fake.responses[sdmx_url + "?detail=allstubs"] = HttpResult(
            response=fake_response(200, text="<ok/>", headers={"content-type": "application/xml"}),
            err=None,
            ssl_fallback_used=None,
        )
        captured: dict = {}

        def _fake_client(**kw) -> FakeHttpClient:
            captured.update(kw)
            return fake

        monkeypatch.setattr(probe, "HttpClient", _fake_client)
        result = probe.probe_url(sdmx_url)
        assert result.status == "GREEN"
        assert result.http_code == "200"
        assert captured.get("timeout") == probe.SDMX_TIMEOUT_SECONDS
        assert captured.get("timeout") != probe.TIMEOUT_SECONDS
