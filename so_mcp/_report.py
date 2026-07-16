"""
Carica source report e dashboard da data/reports/ (file JSON, non GCS).

I report sono prodotti da build_source_reports.py (CI, weekly) e committati in git.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def source_report(source_id: str) -> dict[str, Any]:
    """Legge il report JSON per una fonte da data/reports/source_reports/."""
    path = REPO_ROOT / "data" / "reports" / "source_reports" / f"{source_id}.json"
    if not path.exists():
        return {"error": f"Report per '{source_id}' non trovato", "source_id": source_id}
    return json.loads(path.read_text())


def dashboard() -> dict[str, Any]:
    """Legge sources_dashboard.json."""
    path = REPO_ROOT / "data" / "reports" / "sources_dashboard.json"
    if not path.exists():
        return {"error": "Dashboard non trovata. Esegui build_source_reports.py prima."}
    return json.loads(path.read_text())
