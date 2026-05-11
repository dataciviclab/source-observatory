#!/usr/bin/env python3
"""Build GitHub issue body for catalog alerts.

Legge diff.md (da catalog_diff.py) e catalog_inventory_report.json.
Scrive issue_title.txt, issue_body.md, issue_labels.json.

Uso:
    python scripts/gha/build_issue_body.py --gcs-prefix gs://bucket/path
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def build_issue(gcs_prefix: str) -> None:
    diff_path = Path("diff.md")
    raw = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""

    if raw == "NO_BASELINE":
        print("No baseline — skipping issue creation.")
        return

    new_report = json.loads(
        Path("data/catalog_inventory/generated/catalog_inventory_report.json").read_text(encoding="utf-8")
    )

    sections = re.split(r"^#### ", raw, flags=re.M)
    regressions = recoveries = new_sources = removed = 0
    for section in sections:
        lines = section.splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        section_body = "\n".join(lines[1:])
        if heading == "Regressioni (ok → errore)":
            regressions = len(re.findall(r"^- `([^`]+)`", section_body, re.M))
        elif heading == "Recovery (errore → ok)":
            recoveries = len(re.findall(r"^- `([^`]+)`", section_body, re.M))
        elif heading == "Nuove fonti rilevate":
            new_sources = len(re.findall(r"^- `([^`]+)`", section_body, re.M))
        elif heading == "Fonti rimosse o non piu raggiungibili":
            removed = len(re.findall(r"^- `([^`]+)`", section_body, re.M))

    total_items_new = sum(v.get("rows", 0) for v in new_report.get("sources", {}).values())
    delta_items = 0
    for line in raw.splitlines():
        m = re.search(r"\| `([^`]+)` \| (\d+) \| (\d+) \|", line)
        if m:
            delta_items += int(m.group(3)) - int(m.group(2))

    captured = new_report.get("captured_at", datetime.now(timezone.utc).isoformat())
    date_str = captured[:10]

    parts = []
    if regressions:
        parts.append(f"{regressions} regressione{'e' if regressions==1 else 'i'}")
    if new_sources:
        parts.append(f"{new_sources} nuova fonte")
    if recoveries:
        parts.append(f"{recoveries} recovery")
    if removed:
        parts.append(f"{removed} rimossa")
    if delta_items:
        parts.append(f"{delta_items:+d} item")
    title = f"[Catalog] {date_str}"
    if parts:
        title += " — " + ", ".join(parts)
    else:
        title += " — variazioni"

    gcs_path = gcs_prefix.replace("gs://", "").rstrip("/")

    body = ["## Sommario inventario"]
    body.append(f"- Nuove fonti: **{new_sources}**")
    body.append(f"- Rimosse: **{removed}**")
    body.append(f"- Regressioni: **{regressions}**")
    body.append(f"- Recovery: **{recoveries}**")
    body.append(f"- Variazione item: **{delta_items:+d}** (totale: {total_items_new})")
    body.append("")
    body.append("## Dettaglio")
    # Tronca le righe troppo lunghe (es. SPARQL query, traceback Python) a 200 caratteri
    _truncated_lines = []
    for _line in raw.splitlines():
        _truncated_lines.append(_line if len(_line) <= 200 else _line[:200] + "...")
    body.append("\n".join(_truncated_lines))
    body.append("")
    stamp = captured[:10].replace("-", "")
    body.append("## Risorse")
    body.append(f"- [Snapshot GCS](https://console.cloud.google.com/storage/browser/{gcs_path}/snapshots/catalog_inventory_{stamp}.parquet)")
    body.append(f"- [Report JSON](https://console.cloud.google.com/storage/browser/{gcs_path}/snapshots/catalog_inventory_report_{stamp}.json)")
    body.append("- [Radar summary](../../data/radar/radar_summary.json)")

    labels = ["catalog-alert"]
    if regressions:
        labels.append("catalog-regression")
    if new_sources:
        labels.append("catalog-new-source")
    if recoveries:
        labels.append("catalog-recovery")

    Path("issue_title.txt").write_text(title, encoding="utf-8")
    Path("issue_body.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    Path("issue_labels.json").write_text(json.dumps(labels), encoding="utf-8")
    print(f"Title: {title}")
    print(f"Labels: {labels}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gcs-prefix", required=True, help="GCS prefix (es. gs://bucket/path)")
    args = p.parse_args()
    build_issue(args.gcs_prefix)


if __name__ == "__main__":
    main()
