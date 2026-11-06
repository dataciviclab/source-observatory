"""Test ``sync_datasets_in_use`` — grouping ACB e update del registry.

Le funzioni pure sono testate senza rete. Il fetch è testato con un client
finto, così il contratto ACB resta verificato senza dipendere dal branch
``context``.
"""

from __future__ import annotations

import pytest
import yaml

from scripts.sync_datasets_in_use import (
    fetch_topic_index,
    group_by_source_id,
    update_registry,
)

pytestmark = pytest.mark.pure_unit


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeResult:
    def __init__(self, payload=None, *, ok=True, err=None):
        self.is_ok = ok
        self.response = _FakeResponse(payload) if payload is not None else None
        self.err = err


class _FakeClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.result


def test_fetch_topic_index():
    payload = {
        "schema_version": 7,
        "generated_at": "2026-11-06T13:50:19",
        "datasets": {"anac": [{"slug": "anac_bandi_gara"}]},
    }
    client = _FakeClient(_FakeResult(payload))

    result = fetch_topic_index("https://example.test/topic_index.json", client=client)

    assert result == payload
    assert client.calls[0][0] == "https://example.test/topic_index.json"
    assert client.calls[0][1]["allow_redirects"] is True


def test_fetch_topic_index_network_error():
    client = _FakeClient(_FakeResult(ok=False, err=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="ACB fetch failed"):
        fetch_topic_index("https://example.test/topic_index.json", client=client)


def test_fetch_topic_index_invalid_payload():
    client = _FakeClient(_FakeResult({"schema_version": 7}))

    with pytest.raises(ValueError, match="missing 'datasets'"):
        fetch_topic_index("https://example.test/topic_index.json", client=client)


def test_group_by_source_id():
    topic_index = {
        "datasets": {
            "anac": [{"slug": "anac_bandi_gara"}, {"slug": "anac_aggiudicazioni"}],
            "inps": [{"slug": "inps_precariato"}],
            "empty": [],
            "bad": [{"nope": 1}, "not-a-card"],
        }
    }

    groups = group_by_source_id(topic_index)

    assert groups == {
        "anac": ["anac_aggiudicazioni", "anac_bandi_gara"],
        "inps": ["inps_precariato"],
    }


def test_update_registry_updates(tmp_path):
    registry = tmp_path / "sources_registry.yaml"
    registry.write_text(
        "anac:\n  protocol: ckan\n  datasets_in_use: [old_slug]\ninps:\n  protocol: ckan\n",
        encoding="utf-8",
    )

    updated = update_registry(
        registry,
        {"anac": ["anac_bandi_gara", "anac_aggiudicazioni"]},
    )

    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert updated == 1
    assert data["anac"]["datasets_in_use"] == [
        "anac_aggiudicazioni",
        "anac_bandi_gara",
    ]
    assert data["inps"].get("datasets_in_use", []) == []


def test_update_registry_unchanged(tmp_path):
    registry = tmp_path / "sources_registry.yaml"
    registry.write_text(
        "anac:\n  protocol: ckan\n  datasets_in_use: [x]\n",
        encoding="utf-8",
    )

    updated = update_registry(registry, {"anac": ["x"]})

    assert updated == 0


def test_update_registry_unknown_source(tmp_path):
    registry = tmp_path / "sources_registry.yaml"
    before = "anac:\n  protocol: ckan\n"
    registry.write_text(before, encoding="utf-8")

    updated = update_registry(registry, {"ghost_fonte": ["slug1"]})

    assert updated == 0
    assert yaml.safe_load(registry.read_text(encoding="utf-8")) == yaml.safe_load(before)


def test_update_registry_dry_run_does_not_write(tmp_path):
    registry = tmp_path / "sources_registry.yaml"
    before = "anac:\n  protocol: ckan\n  datasets_in_use: [old]\n"
    registry.write_text(before, encoding="utf-8")

    updated = update_registry(registry, {"anac": ["new"]}, dry_run=True)

    assert updated == 1
    assert registry.read_text(encoding="utf-8") == before
