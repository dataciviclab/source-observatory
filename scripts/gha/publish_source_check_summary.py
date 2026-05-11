#!/usr/bin/env python3
"""Publish source-check summary to GITHUB_STEP_SUMMARY.

Legge data/catalog_inventory/generated/source_check_results.parquet
e scrive source_check_summary.md.

Uso:
    python scripts/gha/publish_source_check_summary.py
    cat source_check_summary.md >> $GITHUB_STEP_SUMMARY
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> None:
    path = Path("data/catalog_inventory/generated/source_check_results.parquet")
    df = pd.read_parquet(path)
    candidates = int(df["intake_candidate"].sum()) if "intake_candidate" in df.columns else 0
    reachable = int(df["reachable"].sum()) if "reachable" in df.columns else 0
    total = len(df)
    avg_score = df["intake_score"].mean() if "intake_score" in df.columns else 0

    lines = ["## Source check results", ""]
    lines.append(f"- Item in database: {total}")
    if total:
        lines.append(f"- Raggiungibili: {reachable} ({reachable/total*100:.0f}%)")
    lines.append(f"- Intake candidates (score >= 40): {candidates}")
    lines.append(f"- Score medio: {avg_score:.0f}")
    lines.append("")
    if "granularity" in df.columns:
        lines.append("**Granularita:**")
        for gran, n in df["granularity"].value_counts().items():
            lines.append(f"- {gran}: {n}")

    Path("source_check_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
