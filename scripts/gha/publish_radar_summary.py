#!/usr/bin/env python3
"""Publish radar summary to GITHUB_STEP_SUMMARY.

Legge data/radar/radar_summary.json e scrive radar_summary.md.

Uso:
    python scripts/gha/publish_radar_summary.py
    cat radar_summary.md >> $GITHUB_STEP_SUMMARY
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _constants import RADAR_SUMMARY_PATH


def main() -> None:
    summary = json.loads(RADAR_SUMMARY_PATH.read_text(encoding="utf-8"))
    counts = summary.get("status_counts", {})

    lines = ["## Radar status", ""]
    lines.append(f"- Fonti controllate: {summary.get('sources_total', '?')}")
    for status, count in counts.items():
        lines.append(f"- {status}: {count}")
    if summary.get("persistent_red"):
        lines.append("> [!WARNING]")
        lines.append(f"> {summary['persistent_red']} fonti RED persistenti")
        lines.append("")
    for src in summary.get("sources", []):
        flag = "⚠️" if src.get("red_streak", 0) >= 2 else "  "
        lines.append(
            f"{flag} `{src['id']}` — {src['status']} | HTTP {src.get('http_code', '-')} | {src.get('note', '') or 'ok'}"
        )

    Path("radar_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
