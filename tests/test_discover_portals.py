from __future__ import annotations

from pathlib import Path

import pandas as pd

import discover_portals


def test_is_sdmx_xml_rejects_false_positives(monkeypatch) -> None:
    """HTML containing 'sdmx.org' string should not be detected as SDMX."""
    html_with_sdmx_string = '<html><body>For SDMX data visit https://sdmx.org</body></html>'
    assert discover_portals._is_sdmx_xml(html_with_sdmx_string) is False

    # Valid SDMX with Dataflow element
    sdmx_valid = '<?xml version="1.0"?><message:Dataflow xmlns:message="http://www.sdmx.org/2009/message"><message:Dataflow><message:Name>Test</message:Name></message:Dataflow></message:Dataflow>'
    assert discover_portals._is_sdmx_xml(sdmx_valid) is True

    # Valid SDMX with DataStructureDefinition
    sdmx_dsd = '<?xml version="1.0"?><Structure xmlns="http://www.sdmx.org/2009/structure"><DataStructureDefinition><Name>Test</Name></DataStructureDefinition></Structure>'
    assert discover_portals._is_sdmx_xml(sdmx_dsd) is True


def test_probe_ckan_uses_retry(monkeypatch) -> None:
    """_probe_ckan should retry on failure (tested via _retry_get call count)."""
    call_count = 0

    def fake_get(url, timeout=None, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient error")
        from unittest.mock import MagicMixin
        resp = MagicMixin()
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}
        resp.text = '{"success": true, "result": ["a", "b"]}'
        resp.json = lambda: {"success": True, "result": ["a", "b"]}
        return resp

    monkeypatch.setattr(discover_portals, "observatory_get", fake_get)
    discover_portals._DDG_PATHS.clear()

    url = discover_portals._probe_ckan("https://example.gov.it")

    assert url is not None
    assert call_count == 2  # failed once, succeeded on retry


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
    monkeypatch.setattr(discover_portals, "_retry_get", lambda url, timeout: fake_get(url, timeout))
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


def test_refresh_summary_rebuilds_artifacts(tmp_path: Path) -> None:
    df = pd.DataFrame(
        [
            {
                "domain": "example.gov.it",
                "protocol": "ckan",
                "probe_url": "https://example.gov.it/api/3/action/package_list",
                "base_url": "https://example.gov.it",
                "in_registry": "no",
                "source_queries": "q1",
            },
            {
                "domain": "known.gov.it",
                "protocol": "html",
                "probe_url": "",
                "base_url": "https://known.gov.it",
                "in_registry": "yes",
                "source_queries": "q2",
            },
        ]
    )

    summary_path, shortlist_path = discover_portals._write_summary_artifacts(
        df,
        tmp_path / "discovered_portals.parquet",
        "2026-04-20T00:00:00+00:00",
    )

    assert summary_path.exists()
    assert shortlist_path.exists()
    assert "example.gov.it" in summary_path.read_text()
    assert "Portal Scout" in shortlist_path.read_text()
