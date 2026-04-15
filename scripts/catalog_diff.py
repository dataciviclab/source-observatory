#!/usr/bin/env python3
"""
Compara due report di catalog inventory e genera un sommario markdown delle divergenze.
"""
from __future__ import annotations
import json
import argparse
import sys
from pathlib import Path

def load_report(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def is_baseline_empty(report: dict) -> bool:
    """True if the report has no sources — signals a missing baseline (first run)."""
    return not report.get("sources")


def generate_diff(old_report: dict, new_report: dict) -> str:
    old_sources = old_report.get("sources", {})
    new_sources = new_report.get("sources", {})

    all_keys = sorted(set(old_sources.keys()) | set(new_sources.keys()))

    added = []
    removed = []
    changed = []
    regressions = []

    for key in all_keys:
        old_val = old_sources.get(key)
        new_val = new_sources.get(key)

        if old_val is None:
            added.append((key, new_val))
        elif new_val is None:
            removed.append((key, old_val))
        else:
            old_status = old_val.get("status", "ok")
            new_status = new_val.get("status", "ok")
            if old_status == "ok" and new_status != "ok":
                regressions.append((key, new_val))
            elif old_status != "ok" and new_status == "ok":
                # recovery — treat as changed (positive)
                old_rows = old_val.get("rows", 0)
                new_rows = new_val.get("rows", 0)
                changed.append((key, old_rows, new_rows))
            elif old_status == "ok" and new_status == "ok":
                old_rows = old_val.get("rows", 0)
                new_rows = new_val.get("rows", 0)
                if old_rows != new_rows:
                    changed.append((key, old_rows, new_rows))

    if not added and not removed and not changed and not regressions:
        return ""

    lines = ["### Variazioni nel Catalogo", ""]

    if regressions:
        lines.append("#### Regressioni (ok → errore)")
        for key, val in regressions:
            lines.append(f"- `{key}` ({val.get('protocol', 'n/d')}): {val.get('status')} — {val.get('error') or val.get('reason', 'n/d')}")
        lines.append("")

    if added:
        lines.append("#### Nuove fonti rilevate")
        for key, val in added:
            lines.append(f"- `{key}`: {val.get('rows', 0)} item ({val.get('protocol', 'n/d')})")
        lines.append("")

    if removed:
        lines.append("#### Fonti rimosse o non più raggiungibili")
        for key, val in removed:
            lines.append(f"- `{key}` (precedentemente {val.get('rows', 0)} item)")
        lines.append("")

    if changed:
        lines.append("#### Variazione numero item")
        lines.append("| Fonte | Precedente | Attuale | Delta |")
        lines.append("| :--- | :---: | :---: | :---: |")
        for key, old_r, new_r in changed:
            delta = new_r - old_r
            delta_str = f"+{delta}" if delta > 0 else str(delta)
            lines.append(f"| `{key}` | {old_r} | {new_r} | **{delta_str}** |")
        lines.append("")

    lines.append(f"Calcolato il: {new_report.get('captured_at', 'n/d')}")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old_report", help="Path al report JSON precedente")
    parser.add_argument("new_report", help="Path al report JSON attuale")
    parser.add_argument("--output", help="Path al file markdown di output (opzionale)")
    args = parser.parse_args()
    
    try:
        old_data = load_report(args.old_report)
        new_data = load_report(args.new_report)
    except Exception as e:
        print(f"Errore caricamento report: {e}", file=sys.stderr)
        sys.exit(1)
        
    markdown = generate_diff(old_data, new_data)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(markdown)
    else:
        print(markdown)

if __name__ == "__main__":
    main()
