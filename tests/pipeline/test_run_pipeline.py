"""
Test run_pipeline — merge/validate orchestration (con fake_http).

Copre il path nuovo del client condiviso con circuit breaker:
``_validate_one`` deve passare il client al validatore, e ``run_validate``
deve creare un solo client per tutta la run.

Marker: pure_unit (nessuna chiamata HTTP reale).
"""

from __future__ import annotations

import json
import threading
import time

import pandas as pd
import pytest
from lab_connectors.http import HttpResult
from lab_connectors.testing import fake_response

pytestmark = pytest.mark.pure_unit

MEF_URL = (
    "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/"
    "contenuti/REG_tipo_reddito_2025.csv?d=1615465800"
)
# L'URL con query-string è il dato: il validate lo usa INTERO (regressione #433)


def _make_group_df(suffix: str = "") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "dataset_group": f"mef_irpef/statistiche/reg-tipo-reddito{suffix}",
                "source_id": "mef_irpef",
                "protocol": "ckan",
                "distribution_url": MEF_URL,
                "format": "csv",
                "year_signal": 2025,
            }
        ]
    )


def test_validate_one_with_shared_client(monkeypatch, fake_http):
    """_validate_one passa il client condiviso al validatore."""
    from scripts.pipeline import run_pipeline

    csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n2021,Lombardia,2000\n"
    fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
    # il validate crea client con HttpClient(...) — patchiamo la factory
    # (importata da lab_connectors.http sia in _validate_base sia in run_pipeline)
    monkeypatch.setattr("lab_connectors.http.HttpClient", lambda **kw: fake_http)

    df = _make_group_df()
    result = run_pipeline._validate_one(df, client=fake_http)

    assert result["reachable"] is True
    assert len(result.get("columns", [])) > 0
    # il client passato è stato usato: il fake registra la richiesta
    assert fake_http.requests, "il client condiviso deve essere stato usato"


def test_validate_one_without_client_creates_own(monkeypatch, fake_http):
    """Senza client, _validate_one ne crea uno (comportamento storico)."""
    from scripts.pipeline import run_pipeline

    csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n"
    fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
    # _validate_base importa HttpClient a livello modulo: patchiamo il nome
    # bindato nel modulo consumer (il path lab_connectors.http non basta quando
    # il pacchetto e' installato, non editable)
    monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)

    df = _make_group_df()
    result = run_pipeline._validate_one(df)

    assert result["reachable"] is True


def test_run_validate_uses_shared_client(monkeypatch, fake_http):
    """run_validate crea UN client e lo passa a tutti i gruppi."""
    from scripts.pipeline import run_pipeline

    csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n"
    fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
    monkeypatch.setattr("lab_connectors.http.HttpClient", lambda **kw: fake_http)

    # due gruppi distinti per verificare che il client sia condiviso
    df = pd.concat([_make_group_df("A"), _make_group_df("B")], ignore_index=True)
    results = run_pipeline.run_validate(df, max_groups=2, workers=1)

    ok = [r for r in results if r is not None and r.get("reachable")]
    assert len(ok) == 2


def test_run_validate_uses_source_user_agent(monkeypatch, fake_http):
    """L'UA della riga di inventory vince sull'UA di default."""
    from scripts.pipeline import run_pipeline

    csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n"
    fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
    calls: list[dict] = []

    def fake_client(**kwargs):
        calls.append(kwargs)
        return fake_http

    monkeypatch.setattr("lab_connectors.http.HttpClient", fake_client)

    df = _make_group_df()
    df["user_agent"] = "Browser/1.0"
    results = run_pipeline.run_validate(df, max_groups=1, workers=1)

    assert results[0]["reachable"] is True
    assert calls[0]["user_agent"] == "Browser/1.0"


def test_run_validate_uses_one_client_per_user_agent(monkeypatch, fake_http):
    """UA diversi non condividono lo stesso client/circuit breaker."""
    from scripts.pipeline import run_pipeline

    csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n"
    fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
    calls: list[dict] = []

    def fake_client(**kwargs):
        calls.append(kwargs)
        return fake_http

    monkeypatch.setattr("lab_connectors.http.HttpClient", fake_client)

    first = _make_group_df("A")
    first["user_agent"] = "Browser/1.0"
    second = _make_group_df("B")
    second["user_agent"] = "Browser/2.0"
    df = pd.concat([first, second], ignore_index=True)

    run_pipeline.run_validate(df, max_groups=2, workers=1)

    assert [call["user_agent"] for call in calls] == ["Browser/1.0", "Browser/2.0"]


def test_write_output_records_groups_total(tmp_path):
    """Il summary conserva i gruppi pre-validazione per fonte."""
    from scripts.pipeline.run_pipeline import write_output

    results = [{"source_id": "demo", "reachable": True, "columns": ["a"]}]
    write_output(
        results,
        tmp_path / "validated.parquet",
        tmp_path / "summary.json",
        groups_by_source={"demo": 5},
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["groups_total"] == 5
    assert summary["by_source"]["demo"]["groups_total"] == 5
    assert summary["by_source"]["demo"]["total"] == 1


def test_run_validate_limits_per_host(monkeypatch):
    """Il pool può avere 8 worker, ma un host non supera il limite."""
    from scripts.pipeline import run_pipeline

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_validate(group_df, client=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"dataset_group": group_df.iloc[0]["dataset_group"], "reachable": True}

    monkeypatch.setattr(run_pipeline, "_validate_one", fake_validate)
    monkeypatch.setattr("lab_connectors.http.HttpClient", lambda **kw: object())

    df = pd.DataFrame(
        [
            {
                "dataset_group": f"demo/{i}",
                "source_id": "demo",
                "distribution_url": "https://same-host.test/data.csv",
            }
            for i in range(8)
        ]
    )
    run_pipeline.run_validate(df, workers=8, max_concurrency_per_host=2)

    assert max_active == 2


def test_run_validate_limits_per_source(monkeypatch):
    """Il limite per fonte agisce anche con host diversi."""
    from scripts.pipeline import run_pipeline

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_validate(group_df, client=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"dataset_group": group_df.iloc[0]["dataset_group"], "reachable": True}

    monkeypatch.setattr(run_pipeline, "_validate_one", fake_validate)
    monkeypatch.setattr("lab_connectors.http.HttpClient", lambda **kw: object())

    df = pd.DataFrame(
        [
            {
                "dataset_group": f"demo/{i}",
                "source_id": "demo",
                "max_concurrency": 2,
                "distribution_url": f"https://host-{i}.test/data.csv",
            }
            for i in range(8)
        ]
    )
    run_pipeline.run_validate(df, workers=8, max_concurrency_per_host=4)

    assert max_active == 2
