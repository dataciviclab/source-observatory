"""Test per scripts/resource_monitor.py."""
from __future__ import annotations

import json
from unittest.mock import patch
from xml.etree import ElementTree as ET

import requests

from resource_monitor import (
    annotate_resources,
    diff_fields,
    fetch_sdmx,
    fetch_single_url,
    is_data_link,
    parse_sdmx_resources,
    resource_signature,
    write_diff_summary,
)


# --- is_data_link ---


def test_is_data_link_csv() -> None:
    assert is_data_link("https://example.test/download/data.csv") is True


def test_is_data_link_parquet() -> None:
    assert is_data_link("https://example.test/files/report.parquet") is True


def test_is_data_link_json() -> None:
    assert is_data_link("https://example.test/export/report.json") is True


def test_is_data_link_no_extension() -> None:
    assert is_data_link("https://example.test/datasets/123") is False


def test_is_data_link_html() -> None:
    assert is_data_link("https://example.test/page.html") is False


def test_is_data_link_download_pattern() -> None:
    assert is_data_link("https://example.test/download/something") is True


def test_is_data_link_export_pattern() -> None:
    assert is_data_link("https://example.test/export/dataset/1") is True


# --- resource_signature ---


def test_resource_signature_stable() -> None:
    resource = {
        "id": "abc",
        "url": "https://example.test/data.csv",
        "format": "CSV",
        "name": "Dataset",
        "version": "",
        "last_modified": "2026-01-01",
    }
    sig1 = resource_signature(resource)
    sig2 = resource_signature(resource)
    assert sig1 == sig2
    assert len(sig1) == 40  # SHA1 hex length


def test_resource_signature_changes() -> None:
    r1 = {"id": "abc", "url": "https://example.test/data.csv", "format": "CSV", "name": "Dataset", "version": "", "last_modified": "2026-01-01"}
    r2 = {"id": "abc", "url": "https://example.test/data.csv", "format": "XLSX", "name": "Dataset", "version": "", "last_modified": "2026-01-01"}
    assert resource_signature(r1) != resource_signature(r2)


# --- diff_fields ---


def test_diff_fields_no_changes() -> None:
    old = {"url": "https://example.test/data.csv", "format": "CSV", "name": "Dataset", "last_modified": "2026-01-01"}
    new = dict(old)
    assert diff_fields(new, old) == []


def test_diff_fields_format_changed() -> None:
    old = {"url": "https://example.test/data.csv", "format": "CSV", "name": "Dataset", "last_modified": "2026-01-01"}
    new = {**old, "format": "XLSX"}
    changes = diff_fields(new, old)
    assert len(changes) == 1
    assert "format" in changes[0]
    assert "CSV" in changes[0]
    assert "XLSX" in changes[0]


def test_diff_fields_multiple_changed() -> None:
    old = {"url": "https://example.test/data.csv", "format": "CSV", "name": "Dataset", "last_modified": "2026-01-01"}
    new = {**old, "format": "XLSX", "last_modified": "2026-04-01"}
    changes = diff_fields(new, old)
    assert len(changes) == 2


# --- annotate_resources ---


def test_annotate_resources_new() -> None:
    result_resources = [{"id": "r1", "url": "https://example.test/new.csv", "format": "CSV", "name": "New", "version": "", "last_modified": "2026-04-01", "signature": "sig1"}]
    old_index = {}
    annotated, counts = annotate_resources(
        type("FakeResult", (), {"resources": result_resources, "error": None})(),
        old_index,
    )
    assert len(annotated) == 1
    assert annotated[0]["status"] == "new"
    assert counts["new"] == 1


def test_annotate_resources_unchanged() -> None:
    resource = {"id": "r1", "url": "https://example.test/data.csv", "format": "CSV", "name": "Data", "version": "", "last_modified": "2026-01-01", "signature": "same_sig"}
    old_index = {"r1": dict(resource)}
    annotated, counts = annotate_resources(
        type("FakeResult", (), {"resources": [resource], "error": None})(),
        old_index,
    )
    assert len(annotated) == 1
    assert annotated[0]["status"] == "unchanged"
    assert counts["unchanged"] == 1


def test_annotate_resources_changed() -> None:
    old = {"id": "r1", "url": "https://example.test/data.csv", "format": "CSV", "name": "Data", "version": "", "last_modified": "2026-01-01", "signature": "old_sig"}
    new = {"id": "r1", "url": "https://example.test/data.csv", "format": "XLSX", "name": "Data", "version": "", "last_modified": "2026-04-01", "signature": "new_sig"}
    old_index = {"r1": dict(old)}
    annotated, counts = annotate_resources(
        type("FakeResult", (), {"resources": [new], "error": None})(),
        old_index,
    )
    assert len(annotated) == 1
    assert annotated[0]["status"] == "changed"
    assert counts["changed"] == 1
    assert "format" in str(annotated[0]["changes"])


def test_annotate_resources_removed() -> None:
    old_resource = {"id": "r1", "url": "https://example.test/old.csv", "format": "CSV", "name": "Old", "version": "", "last_modified": "2026-01-01", "signature": "old_sig"}
    old_index = {"r1": dict(old_resource)}
    annotated, counts = annotate_resources(
        type("FakeResult", (), {"resources": [], "error": None})(),
        old_index,
    )
    removed = [r for r in annotated if r["status"] == "removed"]
    assert len(removed) == 1
    assert counts["removed"] == 1


# --- parse_sdmx_resources ---


def test_parse_sdmx_resources_minimal() -> None:
    """Parse SDMX XML with a single dataflow."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
                   xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
                   xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
      <mes:Structures>
        <str:Dataflows>
          <str:Dataflow id="DF_1" agencyID="ISTAT" version="1.0">
            <com:Name xml:lang="en">Dataflow One</com:Name>
          </str:Dataflow>
        </str:Dataflows>
      </mes:Structures>
    </mes:Structure>
    """
    source = {"id": "istat", "flow_id": None}
    resources = parse_sdmx_resources(xml, source)
    assert len(resources) == 1
    assert resources[0]["id"] == "DF_1"
    assert resources[0]["name"] == "Dataflow One"
    assert resources[0]["format"] == "SDMX"


def test_parse_sdmx_resources_multiple() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
                   xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
                   xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
      <mes:Structures>
        <str:Dataflows>
          <str:Dataflow id="DF_ALPHA" agencyID="ISTAT" version="1.0">
            <com:Name xml:lang="en">Alpha Flow</com:Name>
          </str:Dataflow>
          <str:Dataflow id="DF_BETA" agencyID="ISTAT" version="2.0">
            <com:Name xml:lang="en">Beta Flow</com:Name>
          </str:Dataflow>
        </str:Dataflows>
      </mes:Structures>
    </mes:Structure>
    """
    source = {"id": "istat"}
    resources = parse_sdmx_resources(xml, source)
    assert len(resources) == 2
    assert resources[0]["id"] == "DF_ALPHA"
    assert resources[1]["id"] == "DF_BETA"


def test_parse_sdmx_resources_flow_filter() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
                   xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
                   xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
      <mes:Structures>
        <str:Dataflows>
          <str:Dataflow id="DF_1" agencyID="ISTAT" version="1.0">
            <com:Name xml:lang="en">Flow One</com:Name>
          </str:Dataflow>
          <str:Dataflow id="DF_2" agencyID="ISTAT" version="1.0">
            <com:Name xml:lang="en">Flow Two</com:Name>
          </str:Dataflow>
        </str:Dataflows>
      </mes:Structures>
    </mes:Structure>
    """
    source = {"id": "istat", "flow_id": "DF_2"}
    resources = parse_sdmx_resources(xml, source)
    assert len(resources) == 1
    assert resources[0]["id"] == "DF_2"


def test_parse_sdmx_resources_empty() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message">
      <mes:Structures>
      </mes:Structures>
    </mes:Structure>
    """
    source = {"id": "istat"}
    resources = parse_sdmx_resources(xml, source)
    assert len(resources) == 0


def test_fetch_single_url_reads_headers_with_context_manager() -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self.headers = {
                "ETag": "abc123",
                "Last-Modified": "Wed, 01 Jan 2026 00:00:00 GMT",
                "Content-Type": "text/csv",
                "Content-Length": "42",
            }

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

    source = {"id": "single", "adapter_type": "single_url", "url": "https://example.test/data.csv"}
    with patch("resource_monitor.requests.get", return_value=FakeResponse()):
        result = fetch_single_url(source, timeout=5)
    assert result.error is None
    assert len(result.resources) == 1
    assert result.resources[0]["etag"] == "abc123"
    assert result.resources[0]["content_length"] == "42"


def test_fetch_sdmx_returns_error_on_request_exception() -> None:
    source = {"id": "sdmx", "adapter_type": "sdmx", "api_url": "https://example.test/sdmx"}
    with patch(
        "resource_monitor.requests.get",
        side_effect=requests.RequestException("network down"),
    ):
        result = fetch_sdmx(source, timeout=5)
    assert result.error is not None
    assert "SDMX fetch failed" in result.error


def test_fetch_sdmx_returns_error_on_xml_parse_error() -> None:
    class FakeResponse:
        text = "<invalid"

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

    source = {"id": "sdmx", "adapter_type": "sdmx", "api_url": "https://example.test/sdmx"}
    with patch("resource_monitor.requests.get", return_value=FakeResponse()):
        with patch(
            "resource_monitor.parse_sdmx_resources",
            side_effect=ET.ParseError("bad xml"),
        ):
            result = fetch_sdmx(source, timeout=5)
    assert result.error is not None
    assert "SDMX XML parse error" in result.error


def test_write_diff_summary_writes_minimal_machine_readable_payload(
    tmp_path, monkeypatch
) -> None:
    reports_dir = tmp_path / "reports"
    diff_path = reports_dir / "diff_summary.json"
    monkeypatch.setattr("resource_monitor.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("resource_monitor.DIFF_SUMMARY_PATH", diff_path)

    snapshot = {
        "generated_at": "2026-04-12T14:00:00+00:00",
        "generated_at_utc": "2026-04-12 14:00:00Z",
        "source_count": 1,
        "sources": [
            {
                "id": "inps-ckan",
                "new_count": 1,
                "changed_count": 1,
                "removed_count": 1,
                "unchanged_count": 3,
                "error": None,
                "resources": [
                    {
                        "id": "r-new",
                        "name": "Nuovo file",
                        "format": "CSV",
                        "url": "https://example.test/new.csv",
                        "status": "new",
                    },
                    {
                        "id": "r-chg",
                        "name": "File aggiornato",
                        "format": "CSV",
                        "url": "https://example.test/changed.csv",
                        "status": "changed",
                        "changes": ["last_modified: 'a' -> 'b'"],
                    },
                    {
                        "id": "r-del",
                        "name": "File rimosso",
                        "format": "CSV",
                        "url": "https://example.test/removed.csv",
                        "status": "removed",
                    },
                ],
            }
        ],
    }

    write_diff_summary(snapshot)
    assert diff_path.exists()

    payload = json.loads(diff_path.read_text(encoding="utf-8"))
    assert payload["source_count"] == 1
    assert payload["sources_with_changes"] == ["inps-ckan"]
    assert payload["sources_with_errors"] == []
    assert payload["per_source"]["inps-ckan"]["new"] == 1
    assert payload["per_source"]["inps-ckan"]["changed"] == 1
    assert payload["per_source"]["inps-ckan"]["removed"] == 1
    assert payload["per_source"]["inps-ckan"]["new_resources"][0]["id"] == "r-new"
    assert payload["per_source"]["inps-ckan"]["changed_resources"][0]["id"] == "r-chg"
    assert payload["per_source"]["inps-ckan"]["removed_resources"][0]["id"] == "r-del"
