"""Test per scripts/catalog/pattern_probes.py."""

from __future__ import annotations

import pytest

from scripts.catalog.pattern_probes import (
    compute_new_content_trigger,
    probe_pattern,
    run_pattern_probes,
)


class TestProbePattern:
    @pytest.mark.pure_unit
    def test_available_2xx(self, monkeypatch):
        class FakeResp:
            status_code = 200
            content = b"x" * 100

        class FakeResult:
            is_ok = True
            response = FakeResp()
            err = None

        class FakeClient:
            def __init__(self, **kw): ...
            def get(self, url, **kw):
                return FakeResult()

        monkeypatch.setattr("scripts.catalog.pattern_probes.HttpClient", FakeClient)
        r = probe_pattern("https://ex.it/2026.csv.zip")
        assert r["available"] is True
        assert r["http_code"] == "200"
        assert r["content_length"] == 100

    @pytest.mark.pure_unit
    def test_unavailable_4xx(self, monkeypatch):
        class FakeResp:
            status_code = 404
            content = b""

        class FakeResult:
            is_ok = True
            response = FakeResp()
            err = None

        class FakeClient:
            def __init__(self, **kw): ...
            def get(self, url, **kw):
                return FakeResult()

        monkeypatch.setattr("scripts.catalog.pattern_probes.HttpClient", FakeClient)
        r = probe_pattern("https://ex.it/2026.csv.zip")
        assert r["available"] is False
        assert r["http_code"] == "404"
        assert r["content_length"] is None

    @pytest.mark.pure_unit
    def test_error_is_unavailable(self, monkeypatch):
        class FakeResult:
            is_ok = False
            response = None
            err = RuntimeError("SSL fail")

        class FakeClient:
            def __init__(self, **kw): ...
            def get(self, url, **kw):
                return FakeResult()

        monkeypatch.setattr("scripts.catalog.pattern_probes.HttpClient", FakeClient)
        r = probe_pattern("https://ex.it/x")
        assert r["available"] is False
        assert "SSL" in r["error"]


class TestRunPatternProbes:
    @pytest.mark.pure_unit
    def test_runs_all_and_names(self, monkeypatch):
        monkeypatch.setattr(
            "scripts.catalog.pattern_probes.probe_pattern",
            lambda url: {"url": url, "available": True, "http_code": "200"},
        )
        results = run_pattern_probes(
            [
                {"name": "fsc-2026", "url": "https://ex.it/2026.zip"},
                {"url": "https://ex.it/2025.zip"},
                {"url": ""},  # skippato
            ]
        )
        assert len(results) == 2
        assert results[0]["name"] == "fsc-2026"
        assert "name" not in results[1]


class TestComputeNewContentTrigger:
    @pytest.mark.pure_unit
    def test_first_run_available_fires(self):
        current = [{"url": "https://x/2026.zip", "available": True}]
        assert compute_new_content_trigger(current, None) is True

    @pytest.mark.pure_unit
    def test_newly_available_fires(self):
        prev = {"pattern_probes": [{"url": "https://x/2026.zip", "available": False}]}
        current = [{"url": "https://x/2026.zip", "available": True}]
        assert compute_new_content_trigger(current, prev) is True

    @pytest.mark.pure_unit
    def test_still_available_no_fire(self):
        prev = {"pattern_probes": [{"url": "https://x/2026.zip", "available": True}]}
        current = [{"url": "https://x/2026.zip", "available": True}]
        assert compute_new_content_trigger(current, prev) is False

    @pytest.mark.pure_unit
    def test_all_down_no_fire(self):
        prev = {"pattern_probes": [{"url": "https://x/2026.zip", "available": False}]}
        current = [{"url": "https://x/2026.zip", "available": False}]
        assert compute_new_content_trigger(current, prev) is False
