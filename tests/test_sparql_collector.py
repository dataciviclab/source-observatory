"""
Test collectors/sparql.py — collect e validate_items (con execute_sparql mockato).

Nessuna rete: execute_sparql (da lab_connectors.http.sparql) è mockato.
Nota: _endpoint_cache è module-level, quindi ogni test usa un endpoint
diverso per evitare contaminazione.
"""

from __future__ import annotations

import pytest

from scripts.collectors import sparql as sparql_collector
from scripts.collectors.base import CollectorResult

pytestmark = pytest.mark.pure_unit


def _cfg(endpoint: str = "https://example.test/sparql") -> dict:
    return {
        "source_kind": "catalog",
        "protocol": "sparql",
        "base_url": endpoint,
        "sparql": {"endpoint_url": endpoint, "limit": 100},
    }


# ── collect ───────────────────────────────────────────────────────────────────


def test_collect_ok(monkeypatch):
    """Enumerazione named graphs → righe con item_id e title leggibile."""
    monkeypatch.setattr(
        sparql_collector,
        "execute_sparql",
        lambda ep, q, timeout: [
            {"g": "https://example.test/graph/Contratto_Pubblico"},
            {"g": ""},  # graph vuoto → skippato
            {"g": "https://example.test/graph/Altro"},
        ],
    )
    result = sparql_collector.collect("fonte", _cfg(), "2026-08-01")
    assert isinstance(result, CollectorResult)
    assert len(result.rows) == 2
    assert result.rows[0]["item_id"] == "https://example.test/graph/Contratto_Pubblico"
    assert result.rows[0]["title"] == "Contratto Pubblico"  # _ → spazio
    assert result.rows[0]["format"] == "SPARQL_NAMED_GRAPH"


def test_collect_error(monkeypatch):
    """Errore di query → warning nel CollectorResult, nessuna riga."""
    monkeypatch.setattr(
        sparql_collector,
        "execute_sparql",
        lambda ep, q, timeout: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = sparql_collector.collect("fonte", _cfg(), "2026-08-01")
    assert result.rows == []
    assert result.warning is not None
    assert result.warning["type"] == "sparql_error"


# ── validate_items ────────────────────────────────────────────────────────────


def test_validate_no_items():
    """Lista vuota → errore 'No items', non crasha."""
    result = sparql_collector.validate_items([])
    assert result["reachable"] is False
    assert "No items" in result["error"]


def test_validate_no_endpoint():
    """Item senza endpoint → errore 'No SPARQL endpoint'."""
    items = [{"source_id": "x", "item_id": "g1", "dataset_group": "x/g1"}]
    result = sparql_collector.validate_items(items)
    assert result["reachable"] is False
    assert "No SPARQL endpoint" in result["error"]


def test_validate_ok(monkeypatch):
    """Endpoint vivo → reachable True, triple_count valorizzato."""
    monkeypatch.setattr(
        sparql_collector,
        "execute_sparql",
        lambda ep, q, timeout: [{"cnt": "42"}],
    )
    items = [
        {
            "source_id": "fonte",
            "item_id": "https://example.test/graph/g1",
            "dataset_group": "fonte/g1",
            "source_url": "https://ep-ok.example.test/sparql",
        }
    ]
    result = sparql_collector.validate_items(items)
    assert result["reachable"] is True
    assert result["triple_count"] == 42
    assert result["readiness_score"] == 3


def test_validate_error(monkeypatch):
    """Query fallita → reachable False, error valorizzato."""
    monkeypatch.setattr(
        sparql_collector,
        "execute_sparql",
        lambda ep, q, timeout: (_ for _ in ()).throw(TimeoutError("slow")),
    )
    items = [
        {
            "source_id": "fonte",
            "item_id": "https://example.test/graph/g1",
            "dataset_group": "fonte/g1",
            "source_url": "https://ep-fail.example.test/sparql",
        }
    ]
    result = sparql_collector.validate_items(items)
    assert result["reachable"] is False
    assert result["readiness_score"] == 0
    assert result["error"] is not None


def test_validate_uses_endpoint_cache(monkeypatch):
    """Stesso endpoint in 2 gruppi → execute_sparql chiamato UNA volta."""
    calls: list = []

    def fake_execute(ep, q, timeout):
        calls.append(ep)
        return [{"cnt": "7"}]

    monkeypatch.setattr(sparql_collector, "execute_sparql", fake_execute)

    items1 = [
        {
            "source_id": "fonte",
            "item_id": "https://example.test/graph/g1",
            "dataset_group": "fonte/g1",
            "source_url": "https://ep-cache.example.test/sparql",
        }
    ]
    items2 = [
        {
            "source_id": "fonte",
            "item_id": "https://example.test/graph/g2",
            "dataset_group": "fonte/g2",
            "source_url": "https://ep-cache.example.test/sparql",
        }
    ]
    sparql_collector.validate_items(items1)
    sparql_collector.validate_items(items2)
    assert len(calls) == 1  # cache: seconda chiamata senza query
