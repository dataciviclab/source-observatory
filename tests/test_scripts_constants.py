"""Test scripts/_constants.py: stale_reason, radar history, registry I/O."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts._constants import (
    STALE_REASON_TAGS,
    append_radar_probe,
    load_radar_history,
    load_registry,
    save_radar_history,
    save_registry,
    stale_reason_from_exception,
)

pytestmark = pytest.mark.pure_unit


class TestStaleReason:
    def test_500(self):
        assert stale_reason_from_exception(RuntimeError("HTTP 500 — Internal Server Error")) == "source_500"
        assert stale_reason_from_exception(RuntimeError("500")) == "source_500"

    def test_503(self):
        assert stale_reason_from_exception(RuntimeError("503 Service Unavailable")) == "source_503"

    def test_timeout(self):
        assert stale_reason_from_exception(TimeoutError("Connection timed out")) == "timeout"
        assert stale_reason_from_exception(RuntimeError("timed out")) == "timeout"

    def test_ssl(self):
        assert stale_reason_from_exception(RuntimeError("SSL error")) == "ssl_error"
        assert stale_reason_from_exception(RuntimeError("ssl_v3 handshake failed")) == "ssl_error"

    def test_connection_error(self):
        assert stale_reason_from_exception(ConnectionError("Connection refused")) == "connection_error"

    def test_dns(self):
        assert stale_reason_from_exception(RuntimeError("Name or service not known")) == "dns_error"
        assert stale_reason_from_exception(RuntimeError("getaddrinfo failed")) == "dns_error"

    def test_unknown(self):
        assert stale_reason_from_exception(RuntimeError("some weird error")) == "unknown"

    def test_stale_reason_tags_exported(self):
        assert isinstance(STALE_REASON_TAGS, dict)
        assert "source_500" in STALE_REASON_TAGS


class TestRadarHistory:
    def test_load_missing_file(self, tmp_path):
        result = load_radar_history(tmp_path / "nonexistent.json")
        assert result == {}

    def test_load_empty_json(self, tmp_path):
        p = tmp_path / "radar_history.json"
        p.write_text("{}", encoding="utf-8")
        result = load_radar_history(p)
        assert result == {}

    def test_load_corrupt_json(self, tmp_path):
        p = tmp_path / "radar_history.json"
        p.write_text("not json", encoding="utf-8")
        result = load_radar_history(p)
        assert result == {}

    def test_load_real_content(self, tmp_path):
        data = {"probes": [], "captured_at": "2024-01-01"}
        p = tmp_path / "radar_history.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_radar_history(p)
        assert result == data

    def test_save_and_reload(self, tmp_path):
        p = tmp_path / "radar_history.json"
        data = {"probes": [{"probe_date": "2024-01-01", "sources": []}]}
        save_radar_history(data, p)
        assert p.exists()
        reloaded = json.loads(p.read_text(encoding="utf-8"))
        assert reloaded == data

    def test_append_probe_creates_probes_key(self):
        result = append_radar_probe({}, "2024-01-01", [{"id": "s1", "status": "GREEN"}])
        assert len(result["probes"]) == 1
        assert result["probes"][0]["probe_date"] == "2024-01-01"

    def test_append_probe_trims_to_14(self):
        history = {"probes": [{"probe_date": f"2024-01-{d:02d}", "sources": []} for d in range(1, 20)]}
        result = append_radar_probe(history, "2024-01-20", [{"id": "s1", "status": "GREEN"}])
        assert len(result["probes"]) == 14


class TestRegistry:
    def test_load_registry(self, tmp_path):
        p = tmp_path / "registry.yaml"
        p.write_text("istat_sdmx:\n  source_kind: sdmx\n", encoding="utf-8")
        result = load_registry(p)
        assert result == {"istat_sdmx": {"source_kind": "sdmx"}}

    def test_load_registry_not_a_dict(self, tmp_path):
        p = tmp_path / "registry.yaml"
        p.write_text("[not a dict]", encoding="utf-8")
        with pytest.raises(ValueError, match="top-level mapping"):
            load_registry(p)

    def test_load_registry_empty(self, tmp_path):
        p = tmp_path / "registry.yaml"
        p.write_text("", encoding="utf-8")
        result = load_registry(p)
        assert result == {}

    def test_save_registry(self, tmp_path):
        p = tmp_path / "registry.yaml"
        data = {"test_source": {"source_kind": "ckan", "protocol": "ckan"}}
        save_registry(p, data)
        assert p.exists()
        content = p.read_text(encoding="utf-8")
        assert "test_source" in content
        assert "ckan" in content
