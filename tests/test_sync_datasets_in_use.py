"""
Test sync_datasets_in_use.py — grouping DI catalog e update registry.

Funzioni pure testate senza rete: group_by_source_id (raggruppa e ordina)
e update_registry (aggiorna sources_registry.yaml preservando ordine).
"""

from __future__ import annotations

import pytest

from scripts.sync_datasets_in_use import group_by_source_id, update_registry

pytestmark = pytest.mark.pure_unit


def test_group_by_source_id():
    """Raggruppa slug per source_id, ordina, ignora dataset senza source."""
    datasets = [
        {"source_id": "anac", "slug": "anac_bandi_gara"},
        {"source_id": "anac", "slug": "anac_aggiudicazioni"},
        {"source_id": "inps", "slug": "inps_precariato"},
        {"slug": "no_source"},  # senza source_id → ignorato
    ]
    groups = group_by_source_id(datasets)
    assert groups == {
        "anac": ["anac_aggiudicazioni", "anac_bandi_gara"],
        "inps": ["inps_precariato"],
    }


def test_update_registry_updates(tmp_path):
    """Fonte presente con lista diversa → aggiornata, conteggio 1."""
    registry = tmp_path / "sources_registry.yaml"
    registry.write_text(
        "anac:\n  protocol: ckan\n  datasets_in_use: [old_slug]\ninps:\n  protocol: ckan\n",
        encoding="utf-8",
    )
    updated = update_registry(
        registry,
        {"anac": ["anac_bandi_gara", "anac_aggiudicazioni"]},
    )
    assert updated == 1
    content = registry.read_text(encoding="utf-8")
    assert "anac_bandi_gara" in content
    assert "anac_aggiudicazioni" in content
    assert "old_slug" not in content


def test_update_registry_unchanged(tmp_path):
    """Lista identica → nessun aggiornamento."""
    registry = tmp_path / "sources_registry.yaml"
    registry.write_text(
        "anac:\n  protocol: ckan\n  datasets_in_use: [x]\n",
        encoding="utf-8",
    )
    updated = update_registry(registry, {"anac": ["x"]})
    assert updated == 0


def test_update_registry_unknown_source(tmp_path):
    """Fonte non nel registry → skippata, non crasha, scrittura avviene."""
    registry = tmp_path / "sources_registry.yaml"
    registry.write_text("anac:\n  protocol: ckan\n", encoding="utf-8")
    updated = update_registry(registry, {"ghost_fonte": ["slug1"]})
    assert updated == 0
    # il registry e' stato comunque riscritto (yaml round-trip)
    assert registry.exists()
