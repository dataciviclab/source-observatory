"""Test delle funzioni pure per collector HTML (nessun HTTP).

Il motore di estrazione link è in ``lab_connectors.discovery.links``.
Qui testiamo l'orchestrazione SO e le deleghe.
"""

import pytest
from lab_connectors.discovery.links import DataLink

from scripts.collectors.html import (
    _build_row,
    _compute_summary,
    _extract_page_meta,
    _extract_prefix,
    _extract_years,
)

pytestmark = pytest.mark.pure_unit

# ─── _extract_page_meta ───────────────────────────────────────────────────────


def test_extract_page_meta_normal_title():
    """Estrae title da <title> semplice."""
    html = "<html><head><title>My Portal</title></head><body></body></html>"
    meta = _extract_page_meta(html)
    assert meta.get("title") == "My Portal"


def test_extract_page_meta_open_data_prefix():
    """Rimuove prefisso 'Open Data - ' dal title."""
    html = "<html><head><title>Open Data - My Portal</title></head><body></body></html>"
    meta = _extract_page_meta(html)
    assert meta.get("title") == "My Portal"


def test_extract_page_meta_with_description():
    """Estrae description da <meta name='description'>."""
    html = (
        "<html><head><title>Title</title>"
        '<meta name="description" content="A portal description here.">'
        "</head><body></body></html>"
    )
    meta = _extract_page_meta(html)
    assert meta.get("title") == "Title"
    assert meta.get("description") == "A portal description here."


def test_extract_page_meta_no_title():
    """HTML senza <title> → dict vuoto."""
    html = "<html><head></head><body>content</body></html>"
    meta = _extract_page_meta(html)
    assert meta == {}


def test_extract_page_meta_empty_html():
    """Stringa vuota → dict vuoto."""
    meta = _extract_page_meta("")
    assert meta == {}


# ─── _extract_prefix ──────────────────────────────────────────────────────────


def test_extract_prefix_underscore():
    """Filename con underscore → prima parte."""
    assert _extract_prefix("FRM_FARMA_5_20260427") == "FRM"


def test_extract_prefix_uppercase_run():
    """Filename senza underscore → regex match (max 8 char)."""
    assert _extract_prefix("SCUANAGRAFESTAT202526") == "SCUANAGR"


def test_extract_prefix_short_no_underscore():
    """Filename corto (2-8 char) senza underscore → match regex."""
    assert _extract_prefix("abc") == "abc"


def test_extract_prefix_single_char():
    """Filename singolo carattere → fallback filename[:6]."""
    assert _extract_prefix("a") == "a"


def test_extract_prefix_underscore_first():
    """Underscore come primo segmento."""
    assert _extract_prefix("_hidden_file") == ""


# ─── _extract_years ───────────────────────────────────────────────────────────


def test_extract_years_single():
    """Filename con un anno."""
    assert _extract_years("dati_2024.csv") == [2024]


def test_extract_years_multiple():
    """Filename con anni multipli."""
    result = _extract_years("report_2023_2025_final.csv")
    assert 2023 in result
    assert 2025 in result


def test_extract_years_none():
    """Filename senza anni."""
    assert _extract_years("noyears.csv") == []


def test_extract_years_four_digit_pattern():
    """Match 20xx anche per anni futuri (es. 2026)."""
    assert _extract_years("FRM_FARMA_5_20260427.csv") == [2026]


# ─── _build_row ────────────────────────────────────────────────────────────


def test_build_row_minimal():
    """_build_row con solo link minimo (DataLink)."""
    link = DataLink(
        url="https://example.gov.it/data/FRM_FARMA_5_20260427.csv",
        format="CSV",
        title="",
        prefix="FRM",
        years=[2026],
    )
    row = _build_row(link, "test_source", "https://example.gov.it", "sanita")
    assert row["source_id"] == "test_source"
    assert row["protocol"] == "html"
    assert row["distribution_url"] == "https://example.gov.it/data/FRM_FARMA_5_20260427.csv"
    assert row["url"] == row["distribution_url"]  # alias
    assert row["format"] == "CSV"
    assert row["prefix"] == "FRM"
    assert row["year_signal"] == 2026
    assert row["topic"] == "sanita"
    assert row["item_id"] == "FRM_FARMA_5_20260427"


def test_build_row_with_page_meta():
    """_build_row arricchisce title e notes_excerpt da page_meta (DataLink)."""
    link = DataLink(
        url="https://example.gov.it/data/file.csv",
        format="CSV",
        title="",
        prefix="file",
        years=[],
    )
    page_meta = {
        "https://example.gov.it/data/file.csv": {
            "title": "Report Sanitario",
            "description": "Dati sanitari 2024",
        }
    }
    row = _build_row(
        link,
        "test_source",
        "https://example.gov.it",
        "sanita",
        page_meta=page_meta,
        data_page_url="https://example.gov.it/data/file.csv",
    )
    assert row["title"] == "Report Sanitario"
    assert row["notes_excerpt"] == "Dati sanitari 2024"
    assert row["landing_page"] == "https://example.gov.it/data/file.csv"


def test_build_row_no_topic_hint():
    """_build_row senza topic_hint → topic unknown (DataLink)."""
    link = DataLink(
        url="https://example.gov.it/data/file.csv",
        format="CSV",
        title="",
        prefix="file",
        years=[],
    )
    row = _build_row(link, "test_source", "https://example.gov.it", None)
    assert row["topic"] == "unknown"


def test_build_row_no_years():
    """_build_row senza anno nel filename → year_signal None (DataLink)."""
    link = DataLink(
        url="https://example.gov.it/data/noyears.csv",
        format="CSV",
        title="",
        prefix="noyears",
        years=[],
    )
    row = _build_row(link, "test_source", "https://example.gov.it", None)
    assert row["year_signal"] is None


# ─── _compute_summary ──────────────────────────────────────────────────────


def _dl(url: str, fmt: str = "CSV") -> DataLink:
    """Helper: DataLink veloce per test."""
    from urllib.parse import urlparse

    filename = urlparse(url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    from lab_connectors.discovery.links import extract_prefix, extract_years

    return DataLink(
        url=url,
        format=fmt,
        prefix=extract_prefix(filename),
        years=extract_years(filename),
    )


def test_compute_summary_basic():
    """_compute_summary con link semplici."""
    links = [
        _dl("https://ex.it/data/FRM_2024.csv"),
        _dl("https://ex.it/data/FRM_2025.xlsx", "XLSX"),
        _dl("https://ex.it/data/SCU_2024.csv"),
    ]
    summary = _compute_summary(
        links, [], "istruzione", method="csv_magnet_area_pages_direct", area_pages_scanned=2
    )
    assert summary["method"] == "csv_magnet_area_pages_direct"
    assert summary["by_format"] == {"CSV": 2, "XLSX": 1}
    assert summary["years_range"] == [2024, 2025]
    assert summary["topics"] == {"istruzione": 3}
    assert summary["area_pages_scanned"] == 2
    assert summary["total_links_exact"] == 3
    assert "FRM" in summary["prefix_matrix"]
    assert "SCU" in summary["prefix_matrix"]


def test_compute_summary_empty():
    """_compute_summary con lista vuota."""
    summary = _compute_summary([], [], None, method="csv_magnet_homepage_only")
    assert summary["by_format"] == {}
    assert summary["years_range"] == []
    assert summary["topics"] == {}
    assert summary["method"] == "csv_magnet_homepage_only"


def test_compute_summary_sitemap_estimate():
    """_compute_summary con parametri di stima sitemap."""
    links = [
        _dl("https://ex.it/data/FRM_2024.csv"),
        _dl("https://ex.it/data/SCU_2024.csv"),
    ]
    summary = _compute_summary(
        links,
        [],
        "istruzione",
        method="csv_magnet_sitemap_sample",
        total_pages=100,
        pages_probed=2,
        pages_sampled=2,
    )
    assert summary["total_pages_in_sitemap"] == 100
    assert summary["pages_probed"] == 2
    assert summary["links_found_in_sample"] == 2
    assert summary["links_per_page_estimate"] == 1.0
    assert summary["total_links_estimate"] == 100


def test_compute_summary_years_set_correct():
    """_compute_summary: years_range da filename con anni."""
    links = [
        _dl("https://ex.it/data/FRM_2021_2022.csv"),
        _dl("https://ex.it/data/FRM_2023.csv"),
    ]
    summary = _compute_summary(links, [], None, method="test", area_pages_scanned=1)
    assert summary["years_range"] == [2021, 2023]


# ─── Liferay Catalog Parser ──────────────────────────────────────────────────

_LIFERAY_HTML = """\
<html><head><title>Open Data - OpenCivitas</title></head>
<body>
<table>
  <thead><tr><th>Titolo</th><th>Data</th><th>Anno</th><th>Download</th></tr></thead>
  <tbody class="table-group-divider">
    <tr>
      <th scope="row"><a href="https://ex.it/portale/w/entry-1">2023 Comuni - Amministrazione</a></th>
      <td>01/10/2026</td>
      <td>1</td>
      <td class="iconstable">
        <a href="https://ex.it/portale/documents/0/0/2023_Ind_AMMINISTR_01_IT.csv/aaa-111">CSV</a>
        <a href="https://ex.it/portale/documents/0/0/2023_FC90_AMMINISTR_1_IT.rdf/bbb-222">RDF</a>
      </td>
    </tr>
    <tr>
      <th scope="row"><a href="https://ex.it/portale/w/entry-2">2023 Comuni - Polizia</a></th>
      <td>01/10/2026</td>
      <td>1</td>
      <td class="iconstable">
        <a href="https://ex.it/portale/documents/0/0/2023_Ind_POLIZIA_01_IT.csv/ccc-333">CSV</a>
        <a href="https://ex.it/portale/documents/0/0/2025_VAR_FSC_1_2025/ddd-444">CSV</a>
      </td>
    </tr>
  </tbody>
</table>
</body></html>
"""


class TestLiferayCatalogParser:
    @pytest.mark.pure_unit
    def test_extracts_entries_with_title_and_issued(self):
        # Il parser Liferay è annidato in _scan_liferay_catalog.
        # Il test e2e qui sotto copre il comportamento completo.
        import scripts.collectors.html as html_mod

        assert hasattr(html_mod, "_scan_liferay_catalog")

    @pytest.mark.pure_unit
    def test_scan_liferay_catalog_end_to_end(self, monkeypatch):
        from scripts.collectors.html import _scan_liferay_catalog

        class FakeResp:
            status_code = 200
            text = _LIFERAY_HTML
            headers: dict = {}

        class FakeResult:
            is_ok = True
            response = FakeResp()
            err = None
            ssl_fallback_used = False

        class FakeClient:
            def __init__(self, **kw):
                pass

            def get(self, url, **kw):
                return FakeResult()

        monkeypatch.setattr("scripts.collectors.html.HttpClient", FakeClient)
        monkeypatch.setattr("scripts.collectors.html.time.sleep", lambda s: None)

        # Mock HEAD probe per URL extensionless
        def fake_probe_headers(url, **kw):
            return {"status_code": 200, "content_type": "text/csv"}

        monkeypatch.setattr("scripts.collectors.html.probe_url_headers", fake_probe_headers)

        rows, params = _scan_liferay_catalog(
            topic_hint="trasparenza",
            source_id="opencivitas",
            base_url="https://ex.it/portale/open-data",
            page_url_template="https://ex.it/portale/open-data?xpage={page}&xdelta=6",
            page_max=3,
        )
        # 2 entry: entry-1 ha CSV+RDF (2 rows), entry-2 ha CSV+extensionless (2 rows) = 4 rows
        assert len(rows) == 4
        titles = {r["title"] for r in rows}
        assert "2023 Comuni - Amministrazione" in titles
        assert "2023 Comuni - Polizia" in titles
        formats = {r["format"] for r in rows}
        assert "CSV" in formats
        assert "RDF" in formats
        # URL extensionless risolto a CSV via HEAD probe
        extless = [r for r in rows if "2025_VAR_FSC" in r["distribution_url"]]
        assert len(extless) == 1
        assert extless[0]["format"] == "CSV"
        assert params["method"] == "liferay_catalog_table"
        assert "resolved_unknown=1/1" in params.get("format_resolution", "")
