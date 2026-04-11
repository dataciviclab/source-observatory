"""Test per monitor/resource_monitor.py."""
from __future__ import annotations

from monitor.resource_monitor import (
    annotate_resources,
    diff_fields,
    is_data_link,
    parse_sdmx_resources,
    resource_signature,
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
