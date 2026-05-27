"""Test per scripts/gha/gcs_upload.py — _parse_gs_url."""
from __future__ import annotations

import pytest
from gha.gcs_upload import _parse_gs_url

pytestmark = pytest.mark.pure_unit


class TestParseGsUrl:
    @pytest.mark.pure_unit
    def test_full_url(self):
        assert _parse_gs_url("gs://bucket/path/to/file.parquet") == ("bucket", "path/to/file.parquet")

    @pytest.mark.pure_unit
    def test_bucket_only(self):
        assert _parse_gs_url("gs://bucket") == ("bucket", "")

    @pytest.mark.pure_unit
    def test_nested_path(self):
        assert _parse_gs_url("gs://my-bucket/snapshots/catalog_20260522.parquet") == (
            "my-bucket", "snapshots/catalog_20260522.parquet"
        )

    @pytest.mark.pure_unit
    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="gs://"):
            _parse_gs_url("https://bucket/file.txt")
