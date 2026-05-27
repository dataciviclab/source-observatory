"""Test integrazione SO ↔ toolkit.scout.

Verifica che le funzioni condivise da toolkit abbiano i contratti attesi da SO.
Nessuna dipendenza di rete — solo funzioni pure.
"""

import pytest
from toolkit.scout.http import resolve_preview_kind
from toolkit.scout.infer import infer_granularity, infer_years

pytestmark = pytest.mark.contract


def test_preview_kind_uppercase():
    """resolve_preview_kind deve restituire UPPERCASE."""
    assert resolve_preview_kind("http://example.com/data", content_type="text/csv") == "CSV"
    assert resolve_preview_kind("http://example.com/data", content_type="application/json") == "JSON"
    assert resolve_preview_kind("http://example.com/data.xlsx") == "XLSX"
    assert resolve_preview_kind("http://example.com/data.xls") == "XLS"
    assert resolve_preview_kind("http://example.com/data.tsv") == "TSV"
    assert resolve_preview_kind("http://example.com/data.csv") == "CSV"
    assert resolve_preview_kind("http://example.com/data", content_type="text/tab-separated-values") == "TSV"


def test_infer_years_start_regex():
    """infer_years deve catturare anni all'inizio stringa (YEAR_START_RE)."""
    ymin, ymax = infer_years("2023 report annuale")
    assert ymin == 2023
    assert ymax == 2023


def test_infer_years_compact():
    """infer_years deve catturare anni compatti (202122 → 2021-2022)."""
    ymin, ymax = infer_years("202122")
    assert ymin == 2021
    assert ymax == 2022


def test_infer_years_range():
    """infer_years deve catturare range anni."""
    ymin, ymax = infer_years("serie 2015-2023")
    assert ymin == 2015
    assert ymax == 2023


def test_infer_granularity_works():
    """infer_granularity deve riconoscere livelli territoriali."""
    assert infer_granularity("popolazione nei comuni") == "comune"
    assert infer_granularity("dati provinciali") == "provincia"
    assert infer_granularity("statistiche per regione") == "regione"
    assert infer_granularity("dati nazionali") == "nazionale"
    assert infer_granularity("indicatori piemonte") == "regione"
