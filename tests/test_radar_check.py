"""Test per radar_check.py."""

from __future__ import annotations

import json

import radar_check
from collectors.base import SslFallbackFailed, SslFallbackResult


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
    def fake_ssl_get(url, *, timeout=None, allow_redirects=None, stream=None, **kwargs):
        return SslFallbackResult(
            response=FakeResponse(
                status_code=200,
                json_payload={"success": True, "result": []},
            ),
            err=None,
            ssl_fallback_used=None,
        )

    monkeypatch.setattr(radar_check, "observatory_ssl_fallback_get", fake_ssl_get)
    result = radar_check.probe_url("https://demo.test/api/3/action/package_list")
    assert result.status == "GREEN"
    assert result.http_code == "200"
    assert result.ssl_fallback_used is False


def test_probe_url_timeout(monkeypatch) -> None:
    import requests as real_requests

    def fake_ssl_get(url, *, timeout=None, allow_redirects=None, stream=None, **kwargs):
        return SslFallbackResult(
            response=None,
            err=real_requests.exceptions.Timeout("Connection timed out"),
            ssl_fallback_used=False,
        )

    monkeypatch.setattr(radar_check, "observatory_ssl_fallback_get", fake_ssl_get)
    result = radar_check.probe_url("https://slow.test/api/3/action")
    assert result.status == "YELLOW"
    assert "Timeout" in (result.note or "")


def test_probe_url_connection_error(monkeypatch) -> None:
    import requests as real_requests

    def fake_ssl_get(url, *, timeout=None, allow_redirects=None, stream=None, **kwargs):
        return SslFallbackResult(
            response=None,
            err=real_requests.exceptions.ConnectionError("Connection refused"),
            ssl_fallback_used=False,
        )

    monkeypatch.setattr(radar_check, "observatory_ssl_fallback_get", fake_ssl_get)
    result = radar_check.probe_url("https://dead.test/api/3/action")
    assert result.status == "RED"
    assert "Connection error" in (result.note or "")


def test_probe_url_ssl_fallback(monkeypatch) -> None:
    """SSL error first, fallback succeeds — ssl_fallback_used=True.

    observatory_ssl_fallback_get now returns SslFallbackResult with
    ssl_fallback_used=True when primary SSL failed but fallback succeeded.
    """
    def fake_ssl_fallback_get(url, *, timeout=None, allow_redirects=None, stream=None, **kwargs):
        response = FakeResponse(status_code=200, json_payload={"success": True})
        return SslFallbackResult(response=response, err=None, ssl_fallback_used=True)

    monkeypatch.setattr(
        radar_check, "observatory_ssl_fallback_get", fake_ssl_fallback_get
    )
    monkeypatch.setattr(
        radar_check.requests.packages.urllib3,
        "disable_warnings",
        lambda *args, **kwargs: None,
    )

    result = radar_check._probe_once("https://ssl-broken.test/api/3/action")
    assert result.ssl_fallback_used is True
    assert result.status == "GREEN"


def test_observatory_ssl_fallback_get_returns_true_on_fallback_success(monkeypatch) -> None:
    """observatory_ssl_fallback_get returns (response, True) when fallback succeeds.

    New contract: (response, True) = SSL fallback was used and succeeded.
    (response, None) = primary request succeeded.
    The key behavioral difference: callers that check 'if err' still work
    (err is truthy), but now err=True means "fallback succeeded" not "error".
    """
    import requests

    class FakeSuccessResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        url = "https://ssl-broken.test/file.csv"
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class FakePrimarySession:
        """Fake session for the primary (get_observatory_session) path."""
        def __init__(self):
            self.calls = []
        def get(self, url, *, timeout=None, headers=None, verify=None, stream=None, **kwargs):
            self.calls.append({"method": "get", "url": url, "verify": verify})
            if len(self.calls) == 1:
                raise requests.exceptions.SSLError("SSL cert verify failed")
            return FakeSuccessResponse()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class FakeFallbackSessionInstance:
        """Fake session instance returned by requests.Session() in fallback path."""
        def __init__(self):
            self.headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url, *, timeout=None, headers=None, verify=None, stream=None, **kwargs):
            return FakeSuccessResponse()

    class FakeFallbackSessionClass:
        """Fake requests.Session class for the fallback path."""
        def __call__(self):
            return FakeFallbackSessionInstance()
        def __enter__(self): return FakeFallbackSessionInstance()
        def __exit__(self, *a): pass

    from collectors import base
    orig_session = base.get_observatory_session
    orig_requests_session = base.requests.Session
    fake_primary_sessions = []

    def make_fake_session(*a, **k):
        fs = FakePrimarySession()
        fake_primary_sessions.append(fs)
        return fs

    monkeypatch.setattr(base, "get_observatory_session", make_fake_session)
    monkeypatch.setattr(base.requests, "Session", FakeFallbackSessionClass())
    monkeypatch.setattr(base.urllib3, "disable_warnings", lambda *a, **k: None)

    result = base.observatory_ssl_fallback_get("https://ssl-broken.test/file.csv", timeout=10)
    assert result.response is not None
    assert result.err is None
    assert result.ssl_fallback_used is True  # fallback was used and succeeded
    assert len(fake_primary_sessions) == 1  # Only primary was called (fallback uses requests.Session)

    base.get_observatory_session = orig_session
    base.requests.Session = orig_requests_session


def test_observatory_head_retries_verify_false_on_ssl_error(monkeypatch) -> None:
    """observatory_head retries with verify=False when SSLError is raised."""
    import requests

    class FakeSuccessResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        url = "https://ssl-broken.test/"
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class FakePrimarySession:
        """Fake session for the primary (get_observatory_session) path."""
        def __init__(self):
            self.calls = []
        def head(self, url, *, timeout=None, headers=None, verify=None, allow_redirects=None, **kwargs):
            self.calls.append({"method": "head", "url": url, "verify": verify})
            if len(self.calls) == 1:
                raise requests.exceptions.SSLError("SSL cert verify failed")
            return FakeSuccessResponse()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class FakeFallbackSessionInstance:
        """Fake session instance returned by requests.Session() in fallback path."""
        def __init__(self):
            self.headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def head(self, url, *, timeout=None, headers=None, verify=None, allow_redirects=None, **kwargs):
            return FakeSuccessResponse()

    class FakeFallbackSessionClass:
        """Fake requests.Session class for the fallback path."""
        def __call__(self):
            return FakeFallbackSessionInstance()
        def __enter__(self): return FakeFallbackSessionInstance()
        def __exit__(self, *a): pass

    from collectors import base
    orig = base.get_observatory_session
    orig_requests_session = base.requests.Session
    fake_primary_sessions = []

    def make_fake_session(*a, **k):
        fs = FakePrimarySession()
        fake_primary_sessions.append(fs)
        return fs

    monkeypatch.setattr(base, "get_observatory_session", make_fake_session)
    monkeypatch.setattr(base.requests, "Session", FakeFallbackSessionClass())
    monkeypatch.setattr(base.urllib3, "disable_warnings", lambda *a, **k: None)

    resp = base.observatory_head("https://ssl-broken.test/", timeout=10)
    assert resp.status_code == 200
    assert len(fake_primary_sessions) == 1  # Only primary called

    base.get_observatory_session = orig
    base.requests.Session = orig_requests_session


def test_probe_url_ssl_fallback_double_failure(monkeypatch) -> None:
    """SSL error first, fallback also fails — ssl_fallback_used=True, both errors preserved.

    Both primary SSL and fallback failed. result.ssl_fallback_used=False but
    ssl_failure_err is set (from the primary SSLError), so ssl_fallback_used=True
    in the ProbeResult (it correctly reflects that an SSL error occurred).
    """
    import requests as real_requests

    def fake_ssl_fallback_get(url, *, timeout=None, allow_redirects=None, stream=None, **kwargs):
        ssl_exc = real_requests.exceptions.SSLError("SSL cert verify failed")
        fallback_exc = real_requests.exceptions.ConnectionError("Connection refused after fallback")
        return SslFallbackResult(
            response=None,
            err=SslFallbackFailed(ssl_error=ssl_exc, fallback_error=fallback_exc),
            ssl_fallback_used=False,
        )

    monkeypatch.setattr(
        radar_check, "observatory_ssl_fallback_get", fake_ssl_fallback_get
    )
    monkeypatch.setattr(
        radar_check.requests.packages.urllib3,
        "disable_warnings",
        lambda *args, **kwargs: None,
    )

    result = radar_check._probe_once("https://ssl-broken.test/api/3/action")
    # ssl_failure_err is the primary SSLError → ssl_fallback_used=True in ProbeResult
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

    summary, sources_list = radar_check.build_radar_summary(registry, results, "2026-04-18")

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

    # Verifica entry fonte (new lean schema — history-oriented)
    assert len(sources_list) == 2
    sources_by_id = {s["id"]: s for s in sources_list}
    assert "demo_ckan" in sources_by_id
    assert "istat_sdmx" in sources_by_id

    demo = sources_by_id["demo_ckan"]
    assert demo["status"] == "GREEN"
    assert demo["protocol"] == "ckan"
    assert demo["http_code"] == "200"
    assert "note" in demo or demo.get("note") is None

    istat = sources_by_id["istat_sdmx"]
    assert istat["status"] == "YELLOW"
    assert istat["http_code"] == "-"
    assert istat["note"] == "Timeout"

    # Verifica JSON-serializable
    json_str = json.dumps(summary)
    assert isinstance(json_str, str)
    reparsed = json.loads(json_str)
    assert reparsed == summary
