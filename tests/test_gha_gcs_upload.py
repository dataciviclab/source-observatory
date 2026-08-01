"""
Test gha/gcs_upload.py — upload su GCS via CLI (con mock).

Copre i rami di main(): help, file mancante, upload ok.
Nessuna chiamata GCS reale (upload_file mockato).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.pure_unit


def test_help_exits(monkeypatch):
    """--help o usage errato → stampa docstring ed esce 1."""
    from scripts.gha import gcs_upload

    monkeypatch.setattr("sys.argv", ["gcs_upload.py", "-h"])
    with pytest.raises(SystemExit) as exc:
        gcs_upload.main()
    assert exc.value.code == 1

    monkeypatch.setattr("sys.argv", ["gcs_upload.py", "solo-un-arg"])
    with pytest.raises(SystemExit) as exc:
        gcs_upload.main()
    assert exc.value.code == 1


def test_missing_file_exits(monkeypatch, tmp_path):
    """File locale inesistente → errore su stderr, exit 1."""
    from scripts.gha import gcs_upload

    monkeypatch.setattr(
        "sys.argv",
        ["gcs_upload.py", str(tmp_path / "missing.csv"), "gs://bucket/key.csv"],
    )
    with pytest.raises(SystemExit) as exc:
        gcs_upload.main()
    assert exc.value.code == 1


def test_upload_ok(monkeypatch, tmp_path):
    """Upload riuscito → parse URL, upload_file chiamato, OK stampato."""
    from scripts.gha import gcs_upload

    local = tmp_path / "data.csv"
    local.write_text("a,b\n1,2\n")

    uploaded: list[tuple] = []

    def fake_upload_file(path, bucket, key):
        uploaded.append((path, bucket, key))

    monkeypatch.setattr("sys.argv", ["gcs_upload.py", str(local), "gs://my-bucket/data/x.csv"])
    # upload_file e' importato dentro main() da lab_connectors.gcs
    monkeypatch.setattr("lab_connectors.gcs.upload_file", fake_upload_file)

    gcs_upload.main()

    assert uploaded == [(str(local), "my-bucket", "data/x.csv")]
