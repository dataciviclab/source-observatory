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
    def test_empty_200_below_min_bytes_is_unavailable(self, monkeypatch):
        """Regressione #433: MEF risponde 200 + 0 byte per l'anno mancante.

        Con ``min_bytes`` la risposta vuota non conta come disponibile:
        altrimenti il trigger "nuovo contenuto" scatta per sempre.
        """

        class FakeResp:
            status_code = 200
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
        r = probe_pattern("https://ex.it/2026.csv", min_bytes=200)
        assert r["available"] is False
        assert r["http_code"] == "200"
        assert r["content_length"] == 0
        assert r["below_min_bytes"] is True

    @pytest.mark.pure_unit
    def test_above_min_bytes_is_available(self, monkeypatch):
        class FakeResp:
            status_code = 200
            content = b"x" * 500

        class FakeResult:
            is_ok = True
            response = FakeResp()
            err = None

        class FakeClient:
            def __init__(self, **kw): ...
            def get(self, url, **kw):
                return FakeResult()

        monkeypatch.setattr("scripts.catalog.pattern_probes.HttpClient", FakeClient)
        r = probe_pattern("https://ex.it/2026.csv", min_bytes=200)
        assert r["available"] is True
        assert r["content_length"] == 500
        assert "below_min_bytes" not in r

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
            lambda url, min_bytes=0: {"url": url, "available": True, "http_code": "200"},
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

    @pytest.mark.pure_unit
    def test_min_bytes_passed_to_probe(self, monkeypatch):
        """``min_bytes`` dell'entry arriva al probe (sentinelle MEF: 200 + 0 byte)."""
        seen: list[int] = []

        def fake_probe(url, min_bytes=0):
            seen.append(min_bytes)
            return {"url": url, "available": True, "http_code": "200"}

        monkeypatch.setattr("scripts.catalog.pattern_probes.probe_pattern", fake_probe)
        run_pattern_probes(
            [
                {"url": "https://ex.it/2026.csv", "min_bytes": 200},
                {"url": "https://ex.it/2025.csv"},
                {"url": "https://ex.it/2024.csv", "min_bytes": "boh"},
            ]
        )
        assert seen == [200, 0, 0]


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


class TestProbePatternRobustness:
    """Il probe non deve sollevare: gira sul percorso del catalog per ogni URL."""

    @pytest.mark.pure_unit
    def test_body_read_failure_is_inconclusive(self, monkeypatch):
        """Stream resettato durante la lettura → http_code "-", non 4xx finto."""

        class FakeResp:
            status_code = 200

            @property
            def content(self):
                raise RuntimeError("Stream 1 was reset by remote peer")

        class FakeResult:
            is_ok = True
            response = FakeResp()
            err = None

        class FakeClient:
            def __init__(self, **kw): ...

            def get(self, url, **kw):
                return FakeResult()

        monkeypatch.setattr("scripts.catalog.pattern_probes.HttpClient", FakeClient)
        r = probe_pattern("https://ex.it/big.csv")
        assert r["available"] is False
        assert r["http_code"] == "-"
        assert "body read failed" in r["error"]

    @pytest.mark.pure_unit
    def test_read_body_false_does_not_read(self, monkeypatch):
        """Verifica di esistenza: basta lo status, nessuna lettura del corpo."""

        class FakeResp:
            status_code = 200

            @property
            def content(self):
                raise AssertionError("il corpo non deve essere letto")

            def close(self):
                self.closed = True

        class FakeResult:
            is_ok = True
            response = FakeResp()
            err = None

        class FakeClient:
            def __init__(self, **kw): ...

            def get(self, url, **kw):
                return FakeResult()

        monkeypatch.setattr("scripts.catalog.pattern_probes.HttpClient", FakeClient)
        r = probe_pattern("https://ex.it/big.csv", read_body=False)
        assert r["available"] is True
        assert r["http_code"] == "200"
        assert r["content_length"] is None
