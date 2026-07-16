"""
Carica source report e dashboard da data/reports/ (file JSON, non GCS).

I report sono prodotti da build_source_reports.py (CI, weekly) e committati in git.
"""

from __future__ import annotations

import json
from typing import Any

from ._paths import DASHBOARD_PATH, SOURCE_REPORTS_DIR


def source_report(source_id: str) -> dict[str, Any]:
    """Legge il report JSON per una fonte da data/reports/source_reports/."""
    path = SOURCE_REPORTS_DIR / f"{source_id}.json"
    if not path.exists():
        return {"error": f"Report per '{source_id}' non trovato", "source_id": source_id}
    return json.loads(path.read_text())


def dashboard() -> dict[str, Any]:
    """Legge sources_dashboard.json."""
    if not DASHBOARD_PATH.exists():
        return {"error": "Dashboard non trovata. Esegui build_source_reports.py prima."}
    return json.loads(DASHBOARD_PATH.read_text())
