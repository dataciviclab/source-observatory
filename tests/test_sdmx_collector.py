"""Test del collector SDMX (collectors/sdmx.py) — pure functions e collect()."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from lab_connectors.http import HttpResult
from lab_connectors.testing import fake_response

from scripts.collectors import sdmx as sdmx_collector

pytestmark = pytest.mark.pure_unit

# ─── _parse_sdmx_name ─────────────────────────────────────────────────────────


def _name_elem(text: str | None = None) -> ET.Element | None:
    if text is None:
        return None
    elem = ET.Element("{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common}Name")
    elem.text = text
    return elem


def test_parse_name_none():
    """Elemento Name None → ritorna None."""
    assert sdmx_collector.parse_sdmx_name(None) is None


def test_parse_name_empty():
    """Elemento Name con testo vuoto → ritorna None."""
    elem = _name_elem("")
    assert sdmx_collector.parse_sdmx_name(elem) is None


def test_parse_name_valid():
    """Elemento Name con testo → ritorna testo.strip()."""
    elem = _name_elem("  ISTAT Dataflow  ")
    assert sdmx_collector.parse_sdmx_name(elem) == "ISTAT Dataflow"


# ─── _sdmx_api_base ───────────────────────────────────────────────────────────


def test_api_base_none():
    """URL vuota → None."""
    assert sdmx_collector._sdmx_api_base("") is None


def test_api_base_no_dataflow():
    """URL senza /dataflow/ → ritorna URL pulita."""
    result = sdmx_collector._sdmx_api_base("https://example.test/sdmx")
    assert result == "https://example.test/sdmx"


def test_api_base_with_dataflow():
    """URL con /dataflow/ → ritorna base prima di /dataflow/."""
    result = sdmx_collector._sdmx_api_base("https://example.test/SDMXWS/rest/dataflow/IT1")
    assert result == "https://example.test/SDMXWS/rest"


def test_api_base_with_query_string():
    """URL con query string → query eliminata."""
    result = sdmx_collector._sdmx_api_base("https://example.test/sdmx?format=generic")
    assert result == "https://example.test/sdmx"


# ─── catalog_fetch_url (detail=allstubs) ─────────────────────────────────────


def test_catalog_fetch_url_empty():
    """URL vuota → invariata."""
    assert sdmx_collector.catalog_fetch_url("") == ""


def test_catalog_fetch_url_no_query():
    """URL senza query → aggiunge ?detail=allstubs."""
    url = sdmx_collector.catalog_fetch_url("https://example.test/dataflow/IT1")
    assert url == "https://example.test/dataflow/IT1?detail=allstubs"


def test_catalog_fetch_url_with_query():
    """URL con query esistente → aggiunge &detail=allstubs."""
    url = sdmx_collector.catalog_fetch_url("https://example.test/dataflow/IT1?agency=IT1")
    assert url == "https://example.test/dataflow/IT1?agency=IT1&detail=allstubs"


def test_catalog_fetch_url_detail_present():
    """URL con detail già presente → invariata (non duplica)."""
    url = sdmx_collector.catalog_fetch_url("https://example.test/dataflow/IT1?detail=full")
    assert url == "https://example.test/dataflow/IT1?detail=full"


# ─── SDMX XML di esempio per collect() ────────────────────────────────────────

_SDMX_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<message:Structure
    xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
    xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
    xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <message:Structures>
    <structure:Dataflows>
      <structure:Dataflow agencyID="IT1" id="EX1" version="1.0">
        <common:Name xml:lang="en">Example Flow 1</common:Name>
      </structure:Dataflow>
      <structure:Dataflow agencyID="IT1" id="EX2" version="2.0">
        <common:Name xml:lang="en">Example Flow 2</common:Name>
      </structure:Dataflow>
      <structure:Dataflow id="EX3">
        <common:Name xml:lang="en" />
      </structure:Dataflow>
    </structure:Dataflows>
  </message:Structures>
</message:Structure>"""


def test_collect(monkeypatch, fake_http):
    """collect() restituisce righe corrette da XML SDMX."""
    fake_http.responses["https://example.test/dataflow/IT1?detail=allstubs"] = HttpResult(
        response=fake_response(200, _SDMX_XML, headers={"content-type": "application/xml"}),
        err=None,
    )
    monkeypatch.setattr(sdmx_collector, "HttpClient", lambda **kw: fake_http)
    source_cfg = {
        "source_kind": "catalog",
        "protocol": "sdmx",
        "base_url": "https://example.test/dataflow/IT1",
        "catalog_baseline": {"method": "dataflow_count"},
    }
    result = sdmx_collector.collect("test_sdmx", source_cfg, "2026-05-28T12:00:00")

    assert len(result.rows) == 3

    # Primo flow: EX1
    row1 = result.rows[0]
    assert row1["item_id"] == "EX1"
    assert row1["item_name"] == "EX1"
    assert row1["title"] == "Example Flow 1"
    assert row1["ordinal"] == 1
    assert row1["api_base_url"] == "https://example.test"
    assert row1["organization"] == "IT1"
    assert row1["distribution_url"] == "https://example.test/data/EX1/ALL/?format=csv"
    assert row1["format"] == "SDMX"

    # Secondo flow: EX2
    row2 = result.rows[1]
    assert row2["item_id"] == "EX2"
    assert row2["title"] == "Example Flow 2"
    assert row2["ordinal"] == 2

    # Terzo flow: EX3 con Name vuoto → title = None
    row3 = result.rows[2]
    assert row3["item_id"] == "EX3"
    assert row3["title"] is None
    assert row3["ordinal"] == 3


def test_collect_http_error(monkeypatch, fake_http):
    """collect() su errore HTTP → raise RuntimeError."""
    fake_http.responses["https://example.test/dataflow/IT1?detail=allstubs"] = HttpResult(
        response=fake_response(500, "Internal Server Error"),
        err=None,
    )
    monkeypatch.setattr(sdmx_collector, "HttpClient", lambda **kw: fake_http)
    source_cfg = {
        "source_kind": "catalog",
        "protocol": "sdmx",
        "base_url": "https://example.test/dataflow/IT1",
        "catalog_baseline": {"method": "dataflow_count"},
    }
    with pytest.raises(RuntimeError, match="HTTP 500"):
        sdmx_collector.collect("test_sdmx", source_cfg, "2026-05-28T12:00:00")
