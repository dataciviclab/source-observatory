"""
tests/test_portal_scout.py

Story: portal_scout.py probes a source catalog with a small structural sample
and reports what metadata fields are populated and at what rate.

Key behaviours tested here:
  1. CKAN happy path       — package_search returns results → field report
  2. CKAN fallback path    — package_search fails → package_list + package_show
  3. SDMX happy path       — dataflow endpoint reachable → annotation + field report
  4. SPARQL happy path     — bindings returned → field report
  5. Output contract       — every scout returns the same field shape
  6. Error path            — source unreachable → error key, no crash
  7. Dispatcher            — unsupported protocol → skipped
  8. _coverage helper      — edge cases on the utility function
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import portal_scout


# ── FakeResponse ────────────────────────────────────────────────────────────
# portal_scout calls ckan_get_json for CKAN sources. We intercept there.

class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        content_type: str = "application/json",
        payload: dict | None = None,
        text: str = "",
        content: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._payload = payload or {}
        self._text = text
        self._content = content if content is not None else self._text.encode("utf-8")

    def json(self) -> dict:
        return self._payload

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._content

    def raise_for_status(self) -> None:
        pass


# ── Test 1: CKAN happy path ─────────────────────────────────────────────────

def test_scout_ckan_happy_path_returns_populated_field_report(monkeypatch) -> None:
    """
    package_search returns results → scout returns all_fields, temporal_fields,
    format_fields and correct sample_size.
    """
    # Intercept at ckan_get_json — the CKAN HTTP layer
    def fake_ckan_get_json(url, **kwargs):
        assert "package_search" in url, f"unexpected URL: {url}"
        return {
            "success": True,
            "result": {
                "results": [
                    {
                        "id": "pkg-001",
                        "name": "incidenti-comune",
                        "title": "Incidenti per comune",
                        "notes": "Dati incidenti stradali",
                        "author": "Comune di Roma",
                        "metadata_created": "2024-01-01",
                        "metadata_modified": "2024-06-15",
                        "organization": {"title": "Comune di Roma"},
                        "tags": [{"name": "mobilita"}],
                        "num_resources": 1,
                        "license_id": "iodl-2.0",
                        "isopen": True,
                        "resources": [{"format": "CSV"}],
                        "extras": [
                            {"key": "temporal_coverage_from", "value": "2020"},
                            {"key": "temporal_coverage_to", "value": "2023"},
                        ],
                    }
                ]
            },
        }

    monkeypatch.setattr(portal_scout, "ckan_get_json", fake_ckan_get_json)

    result = portal_scout.scout_ckan(
        "lavoro_opendata",
        {"base_url": "https://dati.lavoro.gov.it/SpodCkanApi/api/3/action/package_list"},
    )

    # Output contract
    assert result["protocol"] == "ckan"
    assert result["sample_size"] == 1
    assert "all_fields" in result
    assert "temporal_fields" in result
    assert "format_fields" in result

    # Temporal fields captured from extras
    temporal_keys = list(result["temporal_fields"].keys())
    assert any("temporal" in k for k in temporal_keys)

    # Extra key normalised as a flat field
    assert "extra:temporal_coverage_from" in result["all_fields"]


# ── Test 2: CKAN fallback — package_search raises, package_list works ─────────

def test_scout_ckan_falls_back_to_package_list_when_package_search_raises(monkeypatch) -> None:
    """
    When package_search raises, scout falls back to package_list + package_show.
    The result has the same field-report shape.
    """
    calls: list[str] = []

    def fake_ckan_get_json(url, **kwargs):
        calls.append(url)
        if "package_search" in url:
            raise RuntimeError("search unavailable")
        if "package_list" in url:
            return {"success": True, "result": ["slug-001", "slug-002"]}
        if "package_show" in url:
            return {
                "success": True,
                "result": {
                    "id": "pkg-001",
                    "name": "slug-001",
                    "title": "Dataset from fallback",
                    "notes": "Found via package_list fallback",
                    "organization": {"title": "Test Org"},
                    "tags": [],
                    "resources": [{"format": "XLSX"}],
                    "extras": [
                        {"key": "temporal_coverage_from", "value": "2019"},
                    ],
                },
            }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(portal_scout, "ckan_get_json", fake_ckan_get_json)

    result = portal_scout.scout_ckan(
        "inps",
        {"base_url": "https://serviziweb2.inps.it/odapi/api/3/action/package_list"},
    )

    # Fallback was exercised
    assert any("package_search" in c for c in calls)
    assert any("package_list" in c for c in calls)
    assert any("package_show" in c for c in calls)
    assert any("package_search failed" in e for e in result.get("errors", []))

    # Same output contract as happy path
    assert result["protocol"] == "ckan"
    assert result["sample_size"] == 2  # 2 slugs, both return a valid package
    assert "all_fields" in result
    assert "temporal_fields" in result


# ── Test 3: SDMX happy path ──────────────────────────────────────────────────

def test_scout_sdmx_happy_path_returns_annotation_report(monkeypatch) -> None:
    """
    /dataflow returns a Dataflow with LAYOUT_DATAFLOW_KEYWORDS annotation.
    scout extracts the annotation keys, identifies temporal ones, and returns
    total_dataflows and sample_size.
    """

    # Build a real ET tree — scout parses r.content via ET.fromstring
    ns_str = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
    ns_com = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"

    root = ET.Element("dataflows")
    flow = ET.SubElement(root, f"{{{ns_str}}}Dataflow")
    ET.SubElement(flow, f"{{{ns_com}}}Name").text = "Indicatori GGI"
    ET.SubElement(flow, f"{{{ns_com}}}Description").text = "Gender Governance Indicators"

    # Temporal annotation (should appear in temporal_annotations)
    ann_temporal = ET.SubElement(flow, f"{{{ns_com}}}Annotation")
    ET.SubElement(ann_temporal, f"{{{ns_com}}}AnnotationType").text = "TIME_PERIOD"
    ET.SubElement(ann_temporal, f"{{{ns_com}}}AnnotationText").text = "2000-2024"

    # Keyword annotation (should appear in all_annotations)
    ann_kw = ET.SubElement(flow, f"{{{ns_com}}}Annotation")
    ET.SubElement(ann_kw, f"{{{ns_com}}}AnnotationType").text = "LAYOUT_DATAFLOW_KEYWORDS"
    ET.SubElement(ann_kw, f"{{{ns_com}}}AnnotationText").text = "genere+governance+regione"

    def fake_get(url, **kwargs):
        return FakeResponse(content=ET.tostring(root))

    def fake_sdmx_api_base(url):
        return url.rstrip("/").rsplit("/dataflow", 1)[0]

    monkeypatch.setattr(portal_scout, "observatory_get", fake_get)
    monkeypatch.setattr(portal_scout, "_sdmx_api_base", fake_sdmx_api_base)

    result = portal_scout.scout_sdmx(
        "istat_sdmx",
        {"base_url": "https://esploradati.istat.it/SDMXWS/rest/dataflow/IT1"},
    )

    # Output contract
    assert result["protocol"] == "sdmx"
    assert result["total_dataflows"] == 1
    assert result["sample_size"] == 1
    assert "all_annotations" in result
    assert "temporal_annotations" in result

    # Keyword annotation present
    assert "LAYOUT_DATAFLOW_KEYWORDS" in result["all_annotations"]
    # Temporal annotation identified
    assert "TIME_PERIOD" in result["temporal_annotations"]


# ── Test 4: SPARQL happy path ────────────────────────────────────────────────

def test_scout_sparql_happy_path_returns_field_report(monkeypatch) -> None:
    """
    SPARQL endpoint returns bindings → scout deduplicates by dataset,
    collects fields and returns field report with temporal_fields.
    """

    def fake_get(url, **kwargs):
        return FakeResponse(payload={
            "results": {
                "bindings": [
                    {
                        "dataset": {"type": "uri", "value": "http://ex.it/d1"},
                        "title": {"type": "literal", "value": "Bandi di gara"},
                        "description": {"type": "literal", "value": "Elenco bandi"},
                        "modified": {"type": "literal", "value": "2024-03-01"},
                    },
                    {
                        "dataset": {"type": "uri", "value": "http://ex.it/d2"},
                        "title": {"type": "literal", "value": "Convenzioni"},
                    },
                ]
            }
        })

    def fake_binding_value(row, key):
        b = row.get(key)
        return (b or {}).get("value")

    monkeypatch.setattr(portal_scout, "observatory_get", fake_get)
    monkeypatch.setattr(portal_scout, "sparql_binding_value", fake_binding_value)

    result = portal_scout.scout_sparql(
        "dati_camera",
        {
            "base_url": "https://dati.camera.it/sparql",
            "sparql": {"endpoint_url": "https://dati.camera.it/sparql"},
        },
    )

    assert result["protocol"] == "sparql"
    assert result["sample_size"] == 2
    assert "all_fields" in result
    assert "temporal_fields" in result
    assert "modified" in result["all_fields"]


# ── Test 5: Output contract — all scouts return same top-level keys ───────────

def test_scout_output_contract_protocol_and_sample_size_always_present(monkeypatch) -> None:
    """
    Every scout returns protocol and sample_size in the top-level result,
    regardless of which field-report they use internally.
    """
    # CKAN
    def fake_ckan_get_json(url, **kwargs):
        return {
            "success": True,
            "result": {
                "results": [{
                    "id": "c1", "name": "c1", "title": "C1",
                    "notes": "", "organization": {"title": "T"},
                    "tags": [], "resources": [], "extras": [],
                }]
            },
        }

    monkeypatch.setattr(portal_scout, "ckan_get_json", fake_ckan_get_json)
    ckan_result = portal_scout.scout_ckan("src", {"base_url": "https://x.it/api"})
    assert "protocol" in ckan_result
    assert "sample_size" in ckan_result
    assert ckan_result["protocol"] == "ckan"
    assert ckan_result["sample_size"] == 1

    # SDMX
    def fake_sdmx_get(url, **kwargs):
        root = ET.Element("dataflows")
        ET.SubElement(root, "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure}Dataflow")
        return FakeResponse(content=ET.tostring(root))

    def fake_sdmx_api_base(url):
        return url.rstrip("/").rsplit("/dataflow", 1)[0]

    monkeypatch.setattr(portal_scout, "observatory_get", fake_sdmx_get)
    monkeypatch.setattr(portal_scout, "_sdmx_api_base", fake_sdmx_api_base)
    sdmx_result = portal_scout.scout_sdmx("src", {"base_url": "https://x.it/SDMXWS/rest/dataflow/IT1"})
    assert "protocol" in sdmx_result
    assert "sample_size" in sdmx_result
    assert sdmx_result["protocol"] == "sdmx"

    # SPARQL
    def fake_sparql_get(url, **kwargs):
        return FakeResponse(payload={
            "results": {
                "bindings": [{
                    "dataset": {"type": "uri", "value": "http://ex.it/d1"},
                    "title": {"type": "literal", "value": "T1"},
                }]
            }
        })

    def fake_binding_value(row, key):
        b = row.get(key)
        return (b or {}).get("value")

    monkeypatch.setattr(portal_scout, "observatory_get", fake_sparql_get)
    monkeypatch.setattr(portal_scout, "sparql_binding_value", fake_binding_value)
    sparql_result = portal_scout.scout_sparql("src", {
        "base_url": "https://x.it/sparql",
        "sparql": {"endpoint_url": "https://x.it/sparql"},
    })
    assert "protocol" in sparql_result
    assert "sample_size" in sparql_result
    assert sparql_result["protocol"] == "sparql"


# ── Test 6: Error path ───────────────────────────────────────────────────────

def test_scout_ckan_error_when_both_package_search_and_package_list_fail(monkeypatch) -> None:
    """
    Both package_search AND package_list fail → scout returns {error: ...}
    with no sample_size.  This is the genuine "source unreachable" path.
    Patches ckan_get_json directly so the failure is explicit and deterministic.
    """

    def fake_ckan_get_json(url, **kwargs):
        # Both endpoints fail
        raise RuntimeError("connection refused")

    monkeypatch.setattr(portal_scout, "ckan_get_json", fake_ckan_get_json)

    result = portal_scout.scout_ckan(
        "broken_source",
        {"base_url": "https://broken.gov.it/api/3/action/package_list"},
    )

    assert result["protocol"] == "ckan"
    assert "error" in result
    assert "sample_size" not in result  # no results when everything fails


def test_scout_sdmx_error_on_connection_failure(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        raise RuntimeError("timeout")

    def fake_sdmx_api_base(url):
        return url

    monkeypatch.setattr(portal_scout, "observatory_get", fake_get)
    monkeypatch.setattr(portal_scout, "_sdmx_api_base", fake_sdmx_api_base)

    result = portal_scout.scout_sdmx(
        "istat_sdmx",
        {"base_url": "https://broken.istat.it/SDMXWS/rest/dataflow/IT1"},
    )

    assert result["protocol"] == "sdmx"
    assert "error" in result


# ── Test 7: Dispatcher skips unsupported protocols ───────────────────────────

def test_scout_source_skips_html_and_aem_returns_skipped_true(monkeypatch) -> None:
    """
    scout_source dispatches by protocol. Unknown / non-API protocols
    return {skipped: True, reason: ...}.
    """

    result = portal_scout.scout_source("salute_portal", {"protocol": "html"})
    assert result["protocol"] == "html"
    assert result.get("skipped") is True

    result = portal_scout.scout_source("inail_portal", {"protocol": "aem"})
    assert result["protocol"] == "aem"
    assert result.get("skipped") is True


# ── Test 8: _coverage helper edge cases ─────────────────────────────────────

def test_coverage_with_mixed_values() -> None:
    r = portal_scout._coverage(["a", "b", None, "", []])
    assert r["total_sampled"] == 5
    assert r["populated"] == 2          # "a" and "b"
    assert r["coverage_pct"] == 40
    assert r["samples"] == ["a", "b"]   # first 3 populated, capped at 3


def test_coverage_all_empty() -> None:
    r = portal_scout._coverage([None, "", [], {}])
    assert r["total_sampled"] == 4
    assert r["populated"] == 0
    assert r["coverage_pct"] == 0
    assert r["samples"] == []


def test_coverage_empty_input() -> None:
    r = portal_scout._coverage([])
    assert r["total_sampled"] == 0
    assert r["coverage_pct"] == 0
