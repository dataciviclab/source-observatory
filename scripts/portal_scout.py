#!/usr/bin/env python3
"""
portal_scout.py — sonda strutturale leggera per fonte nel registry.

Non scarica l'intero catalogo. Per ogni fonte sonda un campione minimo
e risponde a: quali campi metadata sono popolati e con che copertura?

Protocolli supportati: ckan, sdmx, sparql
Protocolli skip (non automatizzabili): html, rest, aem

Output: data/portal_scout/{source_id}_scout.json  (o stdout con --dry-run)

Uso:
    python scripts/portal_scout.py
    python scripts/portal_scout.py --source-ids inps openbdap
    python scripts/portal_scout.py --source-ids istat_sdmx --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collectors.base import observatory_get, now_utc_iso, sparql_binding_value
from collectors.ckan import ckan_action_endpoint, ckan_get_json
from collectors.sdmx import parse_sdmx_name, _sdmx_api_base
from collectors.sparql import SPARQL_QUERY_TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"
OUT_DIR = REPO_ROOT / "data" / "portal_scout"

SUPPORTED_PROTOCOLS = {"ckan", "sdmx", "sparql"}
CKAN_SAMPLE_SIZE = 10
SDMX_SAMPLE_SIZE = 10
SPARQL_SAMPLE_SIZE = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coverage(values: list[Any]) -> dict[str, Any]:
    total = len(values)
    populated = sum(1 for v in values if v not in (None, "", [], {}))
    samples = [v for v in values if v not in (None, "", [], {})][:3]
    return {
        "total_sampled": total,
        "populated": populated,
        "coverage_pct": round(populated / total * 100) if total else 0,
        "samples": samples,
    }


def _field_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggrega copertura per ogni campo trovato nel campione."""
    accum: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        for k, v in item.items():
            accum[k].append(v)
    return {field: _coverage(vals) for field, vals in sorted(accum.items())}


# ---------------------------------------------------------------------------
# CKAN scout
# ---------------------------------------------------------------------------

def scout_ckan(source_id: str, source_cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = source_cfg.get("base_url")
    if not base_url:
        return {"protocol": "ckan", "error": "base_url mancante nella configurazione"}
    errors: list[str] = []

    # 1. package_search per sample
    items: list[dict] = []
    try:
        endpoint = ckan_action_endpoint(base_url, "package_search")
        payload = ckan_get_json(endpoint, params={"rows": CKAN_SAMPLE_SIZE, "start": 0})
        items = (payload.get("result") or {}).get("results") or []
    except Exception as exc:
        errors.append(f"package_search failed: {exc}")

    # fallback: package_list + package_show
    if not items:
        try:
            pl_endpoint = ckan_action_endpoint(base_url, "package_list")
            pl = ckan_get_json(pl_endpoint)
            slugs = (pl.get("result") or [])[:CKAN_SAMPLE_SIZE]
            ps_endpoint = ckan_action_endpoint(base_url, "package_show")
            for slug in slugs:
                try:
                    ps = ckan_get_json(ps_endpoint, params={"id": slug})
                    item = ps.get("result") or {}
                    if item:
                        items.append(item)
                except Exception:
                    pass
        except Exception as exc:
            errors.append(f"package_list fallback failed: {exc}")

    if not items:
        return {"protocol": "ckan", "error": "; ".join(errors) or "no items retrieved"}

    # Estrai campi flat + extras normalizzati
    flat_items: list[dict] = []
    for item in items:
        flat: dict[str, Any] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "title": item.get("title"),
            "notes": item.get("notes"),
            "author": item.get("author"),
            "maintainer": item.get("maintainer"),
            "metadata_created": item.get("metadata_created"),
            "metadata_modified": item.get("metadata_modified"),
            "organization": (item.get("organization") or {}).get("title"),
            "tags": [t.get("name") for t in (item.get("tags") or [])],
            "num_resources": item.get("num_resources"),
            "license_id": item.get("license_id"),
            "isopen": item.get("isopen"),
            "resource_formats": list({
                r.get("format") for r in (item.get("resources") or []) if r.get("format")
            }),
        }
        # extras → chiavi individuali per visibilità
        for extra in item.get("extras") or []:
            key = extra.get("key") or ""
            flat[f"extra:{key}"] = extra.get("value")
        flat_items.append(flat)

    field_report = _field_report(flat_items)

    # Evidenzia campi temporali e di formato
    temporal_keys = [k for k in field_report if any(
        tok in k.lower() for tok in ("temporal", "date", "year", "start", "end", "period", "modified", "created")
    )]
    format_keys = [k for k in field_report if any(
        tok in k.lower() for tok in ("format", "resource", "distribution")
    )]

    return {
        "protocol": "ckan",
        "sample_size": len(flat_items),
        "errors": errors or None,
        "temporal_fields": {k: field_report[k] for k in temporal_keys},
        "format_fields": {k: field_report[k] for k in format_keys},
        "all_fields": field_report,
    }


# ---------------------------------------------------------------------------
# SDMX scout
# ---------------------------------------------------------------------------

_SDMX_NS = {
    "mes": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "str": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "com": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}


def scout_sdmx(source_id: str, source_cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = source_cfg.get("base_url")
    if not base_url:
        return {"protocol": "sdmx", "error": "base_url mancante nella configurazione"}
    root_url = _sdmx_api_base(base_url)
    errors: list[str] = []

    try:
        r = observatory_get(f"{root_url}/dataflow", timeout=30)
        r.raise_for_status()
        xml_root = ET.fromstring(r.content)
    except Exception as exc:
        return {"protocol": "sdmx", "error": str(exc)}

    flows = xml_root.findall(".//str:Dataflow", _SDMX_NS)
    sample = flows[:SDMX_SAMPLE_SIZE]

    if not sample:
        return {"protocol": "sdmx", "error": "no dataflows found in response"}

    annotation_keys: dict[str, list[Any]] = defaultdict(list)
    has_name: list[bool] = []
    has_description: list[bool] = []

    for flow in sample:
        name_el = flow.find(".//com:Name", _SDMX_NS)
        has_name.append(bool(parse_sdmx_name(name_el)))

        desc_el = flow.find(".//com:Description", _SDMX_NS)
        has_description.append(desc_el is not None and bool((desc_el.text or "").strip()))

        for ann in flow.findall(".//com:Annotation", _SDMX_NS):
            ann_type = ann.find("com:AnnotationType", _SDMX_NS)
            ann_text = ann.find("com:AnnotationText", _SDMX_NS)
            if ann_type is not None and ann_text is not None:
                key = (ann_type.text or "").strip()
                val = (ann_text.text or "").strip()
                if key:
                    annotation_keys[key].append(val or None)

    ann_report = {
        k: _coverage(vals) for k, vals in sorted(annotation_keys.items())
    }

    temporal_ann = [k for k in ann_report if any(
        tok in k.upper() for tok in ("TIME", "PERIOD", "YEAR", "DATE", "START", "END")
    )]

    return {
        "protocol": "sdmx",
        "total_dataflows": len(flows),
        "sample_size": len(sample),
        "errors": errors or None,
        "core_fields": {
            "Name": _coverage(has_name),
            "Description": _coverage(has_description),
        },
        "temporal_annotations": {k: ann_report[k] for k in temporal_ann},
        "all_annotations": ann_report,
    }


# ---------------------------------------------------------------------------
# SPARQL scout
# ---------------------------------------------------------------------------

def scout_sparql(source_id: str, source_cfg: dict[str, Any]) -> dict[str, Any]:
    sparql_cfg = source_cfg.get("sparql") or {}
    endpoint: str | None = sparql_cfg.get("endpoint_url") or source_cfg.get("base_url")
    if not endpoint:
        return {"protocol": "sparql", "error": "endpoint mancante nella configurazione"}
    query = SPARQL_QUERY_TEMPLATES["dcat_datasets"].replace("{limit}", str(SPARQL_SAMPLE_SIZE))
    errors: list[str] = []

    try:
        r = observatory_get(
            endpoint,
            params={"query": query, "format": "application/sparql-results+json"},
            timeout=30,
            headers={"Accept": "application/sparql-results+json"},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return {"protocol": "sparql", "error": str(exc)}

    bindings = data.get("results", {}).get("bindings") or []
    if not bindings:
        return {"protocol": "sparql", "error": "query returned no bindings", "errors": errors}

    by_dataset: dict[str, dict] = {}
    for row in bindings:
        ds_uri = sparql_binding_value(row, "dataset")
        if not ds_uri:
            continue
        if ds_uri not in by_dataset:
            by_dataset[ds_uri] = {
                "title": None, "description": None, "modified": None,
                "issued": None, "publisher": None, "theme": None, "formats": [],
            }
        rec = by_dataset[ds_uri]
        for field in ("title", "description", "modified", "issued", "publisher", "theme"):
            if rec[field] is None:
                rec[field] = sparql_binding_value(row, field)
        fmt = sparql_binding_value(row, "format")
        if fmt and fmt not in rec["formats"]:
            rec["formats"].append(fmt)

    items = list(by_dataset.values())
    field_report = _field_report([
        {k: (v if k != "formats" else (v or None)) for k, v in item.items()}
        for item in items
    ])

    temporal_keys = [k for k in field_report if any(
        tok in k.lower() for tok in ("modified", "issued", "date", "temporal")
    )]

    return {
        "protocol": "sparql",
        "sample_size": len(items),
        "errors": errors or None,
        "temporal_fields": {k: field_report[k] for k in temporal_keys},
        "all_fields": field_report,
    }


# ---------------------------------------------------------------------------
# Dispatch + main
# ---------------------------------------------------------------------------

def scout_source(source_id: str, source_cfg: dict[str, Any]) -> dict[str, Any]:
    protocol = source_cfg.get("protocol", "")
    if protocol == "ckan":
        return scout_ckan(source_id, source_cfg)
    if protocol == "sdmx":
        return scout_sdmx(source_id, source_cfg)
    if protocol == "sparql":
        return scout_sparql(source_id, source_cfg)
    return {"protocol": protocol, "skipped": True, "reason": f"protocollo '{protocol}' non automatizzabile"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portal scout — sonda strutturale leggera per fonte nel registry.")
    parser.add_argument("--source-ids", nargs="+", metavar="SOURCE_ID", help="Filtra per source_id (default: tutte).")
    parser.add_argument("--dry-run", action="store_true", help="Stampa su stdout invece di scrivere file.")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR, help="Directory output (default: data/portal_scout/).")
    parser.add_argument("--registry-path", type=Path, default=REGISTRY_PATH, help="Path YAML registry alternativo (es. candidati discovery).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.registry_path.open(encoding="utf-8") as fh:
        registry: dict[str, dict] = yaml.safe_load(fh) or {}

    filter_ids = set(args.source_ids) if args.source_ids else None
    scouted_at = now_utc_iso()
    results: dict[str, Any] = {}

    for source_id, source_cfg in registry.items():
        if filter_ids and source_id not in filter_ids:
            continue
        protocol = source_cfg.get("protocol", "")
        if protocol not in SUPPORTED_PROTOCOLS:
            results[source_id] = {"protocol": protocol, "skipped": True, "reason": f"protocollo '{protocol}' non automatizzabile"}
            print(f"  skip  {source_id} ({protocol})")
            continue

        print(f"  scout {source_id} ({protocol}) ...", end=" ", flush=True)
        try:
            result = scout_source(source_id, source_cfg)
        except Exception as exc:
            result = {"protocol": protocol, "error": str(exc)}
        results[source_id] = result
        status = "error" if "error" in result else "ok"
        print(status)

    ok_count = sum(1 for r in results.values() if "error" not in r and "skipped" not in r)
    error_count = sum(1 for r in results.values() if "error" in r)
    skipped_count = sum(1 for r in results.values() if r.get("skipped"))

    summary = {
        "scouted_at": scouted_at,
        "total": len(results),
        "ok": ok_count,
        "error": error_count,
        "skipped": skipped_count,
    }

    output = {"scouted_at": scouted_at, "sources": results}

    if args.dry_run:
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for source_id, result in results.items():
        out_path = args.out_dir / f"{source_id}_scout.json"
        out_path.write_text(json.dumps({"scouted_at": scouted_at, "source_id": source_id, **result}, indent=2, ensure_ascii=False))

    # Write machine-readable summary
    summary_path = args.out_dir / "_scout_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\nScritti {len(results)} report in {args.out_dir}")
    print(f"Summary: {ok_count} ok, {error_count} error, {skipped_count} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
