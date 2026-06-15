"""Test delle funzioni pure di collectors.html (nessun HTTP)."""

import pytest
from collectors.html import (
    _build_row,
    _compute_summary,
    _extract_data_links,
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


# ─── _extract_data_links ───────────────────────────────────────────────────


def test_extract_data_links_finds_csv():
    """Estrae link CSV da HTML."""
    html = '<a href="https://example.gov.it/data.csv">scaricami</a>'
    links = _extract_data_links("https://example.gov.it", html)
    assert len(links) == 1
    assert links[0]["url"] == "https://example.gov.it/data.csv"
    assert links[0]["format"] == "CSV"


def test_extract_data_links_multiple_formats():
    """Estrae link con formati diversi."""
    html = """
        <a href="/data/file1.csv">CSV</a>
        <a href="/data/file2.xlsx">XLSX</a>
        <a href="/data/file3.json">JSON</a>
    """
    links = _extract_data_links("https://example.gov.it", html)
    assert len(links) == 3
    fmts = {lnk["format"] for lnk in links}
    assert fmts == {"CSV", "XLSX", "JSON"}


def test_extract_data_links_skips_non_data():
    """Ignora link a pagine HTML normali."""
    html = """
        <a href="/about">About</a>
        <a href="/contact">Contact</a>
        <a href="/data/report.pdf">PDF</a>
    """
    links = _extract_data_links("https://example.gov.it", html)
    assert len(links) == 0


def test_extract_data_links_skips_anchor_mailto_tel():
    """Ignora ancore, mailto, tel."""
    html = """
        <a href="#section">Sezione</a>
        <a href="mailto:info@example.gov.it">Email</a>
        <a href="tel:+3906123456">Chiama</a>
    """
    links = _extract_data_links("https://example.gov.it", html)
    assert len(links) == 0


def test_extract_data_links_resolves_relative():
    """Risolve URL relativi contro base_url."""
    html = '<a href="data.csv">data</a>'
    links = _extract_data_links("https://example.gov.it/dir/", html)
    assert links[0]["url"] == "https://example.gov.it/dir/data.csv"


def test_extract_data_links_handles_title():
    """Estrae titolo da aria-label o attributo title."""
    html = '<a href="data.csv" aria-label="Report 2024">data</a>'
    links = _extract_data_links("https://example.gov.it", html)
    assert links[0]["title"] == "Report 2024"


def test_extract_data_links_detects_zip():
    """Riconosce estensione ZIP."""
    html = '<a href="https://example.gov.it/archive.zip">ZIP</a>'
    links = _extract_data_links("https://example.gov.it", html)
    assert links[0]["format"] == "ZIP"


# ─── _build_row ────────────────────────────────────────────────────────────


def test_build_row_minimal():
    """_build_row con solo link minimo."""
    link = {
        "url": "https://example.gov.it/data/FRM_FARMA_5_20260427.csv",
        "format": "CSV",
        "title": "",
    }
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
    """_build_row arricchisce title e notes_excerpt da page_meta."""
    link = {"url": "https://example.gov.it/data/file.csv", "format": "CSV", "title": ""}
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
    """_build_row senza topic_hint → topic unknown."""
    link = {"url": "https://example.gov.it/data/file.csv", "format": "CSV", "title": ""}
    row = _build_row(link, "test_source", "https://example.gov.it", None)
    assert row["topic"] == "unknown"


def test_build_row_no_years():
    """_build_row senza anno nel filename → year_signal None."""
    link = {"url": "https://example.gov.it/data/noyears.csv", "format": "CSV", "title": ""}
    row = _build_row(link, "test_source", "https://example.gov.it", None)
    assert row["year_signal"] is None


# ─── _compute_summary ──────────────────────────────────────────────────────


def test_compute_summary_basic():
    """_compute_summary con link semplici."""
    links = [
        {"url": "https://ex.it/data/FRM_2024.csv", "format": "CSV"},
        {"url": "https://ex.it/data/FRM_2025.xlsx", "format": "XLSX"},
        {"url": "https://ex.it/data/SCU_2024.csv", "format": "CSV"},
    ]
    summary = _compute_summary(
        links, "istruzione", method="csv_magnet_area_pages_direct", area_pages_scanned=2
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
    summary = _compute_summary([], None, method="csv_magnet_homepage_only")
    assert summary["by_format"] == {}
    assert summary["years_range"] == []
    assert summary["topics"] == {}
    assert summary["method"] == "csv_magnet_homepage_only"


def test_compute_summary_sitemap_estimate():
    """_compute_summary con parametri di stima sitemap."""
    links = [
        {"url": "https://ex.it/data/FRM_2024.csv", "format": "CSV"},
        {"url": "https://ex.it/data/SCU_2024.csv", "format": "CSV"},
    ]
    summary = _compute_summary(
        links,
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
        {"url": "https://ex.it/data/FRM_2021_2022.csv", "format": "CSV"},
        {"url": "https://ex.it/data/FRM_2023.csv", "format": "CSV"},
    ]
    summary = _compute_summary(links, None, method="test", area_pages_scanned=1)
    assert summary["years_range"] == [2021, 2023]
