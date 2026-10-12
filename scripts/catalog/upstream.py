"""Estrazione riferimenti upstream dai dataset.yml di un repo.

Il legame dataset ↔ item del portale è già dichiarato nei ``dataset.yml``
(ogni repo nel suo modo), ma resta implicito per gli agenti e i consumatori
del catalog. Questo modulo lo rende esplicito in ``datasets_in_use[].upstream``:

  - sdmx   → args.flow          → {kind: "dataflow", id: "DEMO_R_D3DENS"}
  - ckan   → args.resource_id   → {kind: "ckan_resource", id: "<uuid>"}
  - http_file → args.url        → {kind: "url", id: "<url>"}
  - script → args.command con ``--type X`` → {kind: "script_type", id: "X"}

Estrazione conservativa: solo chiavi note, nessun parsing aggressivo dei
comandi. Un dataset senza riferimenti espliciti produce ``upstream: []``
(il campo è opzionale e backward-compatible).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def extract_upstream_from_source(source: dict[str, Any]) -> list[dict[str, str]]:
    """Riferimenti upstream di una singola entry raw.sources[]."""
    stype = str(source.get("type") or "")
    raw_args = source.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    refs: list[dict[str, str]] = []

    if stype == "sdmx" and args.get("flow"):
        ref: dict[str, str] = {"kind": "dataflow", "id": str(args["flow"])}
        if args.get("agency"):
            ref["agency"] = str(args["agency"])
        refs.append(ref)
    elif stype == "ckan" and args.get("resource_id"):
        refs.append({"kind": "ckan_resource", "id": str(args["resource_id"])})
    elif stype in ("http_file", "http_post_file") and args.get("url"):
        refs.append({"kind": "url", "id": str(args["url"])})
    elif stype == "script":
        # upstream_url dichiarato esplicitamente nel dataset.yml
        if args.get("upstream_url"):
            refs.append({"kind": "url", "id": str(args["upstream_url"])})
        # Pattern diffuso: ... --type <value>  (es. prefetch.py --type sentenze)
        if args.get("command"):
            cmd = str(args["command"])
            marker = "--type"
            if marker in cmd:
                tail = cmd.split(marker, 1)[1].strip().split()[0].strip("\"'")
                if tail:
                    refs.append({"kind": "script_type", "id": tail})
    return refs


def extract_upstream_from_dataset_yml(text: str) -> list[dict[str, str]]:
    """Riferimenti upstream aggregati da tutto il dataset.yml."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("raw")
    raw_block: dict[str, Any] = raw if isinstance(raw, dict) else {}
    sources_raw = raw_block.get("sources")
    sources: list[Any] = sources_raw if isinstance(sources_raw, list) else []
    refs: list[dict[str, str]] = []
    for src in sources:
        if isinstance(src, dict):
            refs.extend(extract_upstream_from_source(src))
    # Dedup preservando l'ordine
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for r in refs:
        key = (r["kind"], r["id"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def load_upstream_map(repo_root: Path) -> dict[str, list[dict[str, str]]]:
    """Mappa slug(dataset.name) → upstream refs da datasets/*/dataset.yml.

    Il nome canonicizzato coincide con lo slug del registry.json toolkit.
    Graceful: yml illeggibile o senza name → skippato.
    """
    out: dict[str, list[dict[str, str]]] = {}
    for section in ("datasets", "candidates", "compose", "support"):
        for yml in sorted((repo_root / section).glob("*/dataset.yml")):
            try:
                text = yml.read_text(encoding="utf-8", errors="replace")
                data = yaml.safe_load(text) or {}
            except (yaml.YAMLError, OSError):
                continue
            name = ((data.get("dataset") or {}).get("name")) if isinstance(data, dict) else None
            if not name:
                continue
            out[str(name)] = extract_upstream_from_dataset_yml(text)
    return out
