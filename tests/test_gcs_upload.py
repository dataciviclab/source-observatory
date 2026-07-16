"""Test per lab_connectors.gcs.paths.parse_gs_url.

La funzione era duplicata in scripts/gha/gcs_upload.py, ora vive in lab-connectors.
Questo test verifica che lab-connectors esponga la stessa API.
"""

from __future__ import annotations

import pytest
from lab_connectors.gcs.paths import parse_gs_url

pytestmark = pytest.mark.pure_unit


class TestParseGsUrl:
    @pytest.mark.pure_unit
    def test_full_url(self):
        assert parse_gs_url("gs://bucket/path/to/file.parquet") == (
            "bucket",
            "path/to/file.parquet",
        )

    @pytest.mark.pure_unit
    def test_nested_path(self):
        assert parse_gs_url("gs://my-bucket/snapshots/catalog_20260522.parquet") == (
            "my-bucket",
            "snapshots/catalog_20260522.parquet",
        )

    @pytest.mark.pure_unit
    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="gs://"):
            parse_gs_url("https://bucket/file.txt")
