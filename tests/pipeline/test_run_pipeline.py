"""
Test run_pipeline — merge/validate orchestration (con fake_http).

Copre il path nuovo del client condiviso con circuit breaker:
``_validate_one`` deve passare il client al validatore, e ``run_validate``
deve creare un solo client per tutta la run.

Marker: pure_unit (nessuna chiamata HTTP reale).
"""

from __future__ import annotations

import pandas as pd
import pytest
from lab_connectors.http import HttpResult
from lab_connectors.testing import fake_response

pytestmark = pytest.mark.pure_unit

MEF_URL = (
    "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/"
    "contenuti/REG_tipo_reddito_2025.csv?d=1615465800"
)
MEF_URL_NO_QUERY = MEF_URL.split("?")[0]


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
    fake_http.responses[MEF_URL_NO_QUERY] = HttpResult(
        response=fake_response(200, csv_body), err=None
    )
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
    fake_http.responses[MEF_URL_NO_QUERY] = HttpResult(
        response=fake_response(200, csv_body), err=None
    )
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
    fake_http.responses[MEF_URL_NO_QUERY] = HttpResult(
        response=fake_response(200, csv_body), err=None
    )
    monkeypatch.setattr("lab_connectors.http.HttpClient", lambda **kw: fake_http)

    # due gruppi distinti per verificare che il client sia condiviso
    df = pd.concat([_make_group_df("A"), _make_group_df("B")], ignore_index=True)
    results = run_pipeline.run_validate(df, max_groups=2, workers=1)

    ok = [r for r in results if r is not None and r.get("reachable")]
    assert len(ok) == 2
