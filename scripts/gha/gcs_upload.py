#!/usr/bin/env python3
"""Upload file to GCS via lab_connectors.gcs.

Usage:
    python scripts/gha/gcs_upload.py <local_path> <gs://bucket/path>

Parses gs:// URLs, calls lab_connectors.gcs.upload_file().
Requires: pip install "lab-connectors[gcs]"
"""

from __future__ import annotations

import sys
from pathlib import Path

from lab_connectors.gcs.paths import parse_gs_url


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(1)

    local_path = Path(sys.argv[1])
    gs_url = sys.argv[2]

    if not local_path.exists():
        print(f"ERROR: file non trovato: {local_path}", file=sys.stderr)
        sys.exit(1)

    bucket, key = parse_gs_url(gs_url)
    from lab_connectors.gcs import upload_file

    upload_file(str(local_path), bucket, key)
    print(f"OK: {local_path} → gs://{bucket}/{key}")


if __name__ == "__main__":  # pragma: no cover
    main()
