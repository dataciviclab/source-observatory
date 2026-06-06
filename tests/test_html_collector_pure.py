"""Test delle funzioni pure di collectors.html (nessun HTTP)."""

import pytest
from collectors.html import (
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
