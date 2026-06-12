#!/usr/bin/env python3
"""
joinability_scan.py — Scansione della joinabilità con cross-reference al catalogo.

Legge source_check_results.parquet (da GCS pubblico). Usa le chiavi di join
già pre-calcolate (colonna `join_keys`) se presenti, altrimenti le rileva da
`columns`. Cross-referenzia col catalogo esistente (clean_catalog.json) per
mostrare quali dataset del Lab diventerebbero joinabili, e produce uno score
arricchito (incluso bonus cross-ref).

Output: observatory-results/joinability_report.json (gitignorato)
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any

from _constants import JOIN_KEY_PATTERNS, detect_join_keys, parse_columns
from lab_connectors.duckdb import gcs_connect
from lab_connectors.http import HttpClient

# ── Percorsi ──────────────────────────────────────────────────────────────────
# I path artifact GCS seguono il path contract canonico (lab-connectors/paths.json).
# Il parquet viene letto via DuckDB S3 (httpfs) — niente download HTTP.

SOURCE_CHECK_URL = (
    "s3://dataciviclab-clean/catalog_inventory/source-check/source_check_results.parquet"
)

CATALOG_URL = (
    "https://raw.githubusercontent.com/dataciviclab/"
    "dataset-incubator/main/registry/clean_catalog.json"
)

OUTPUT_REL_DIR = "observatory-results"  # gitignorato in SO

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    OUTPUT_REL_DIR,
    "joinability_report.json",
)


# ── Join key patterns ───────────────────────────────────────────────────────
# I pattern canonici sono in _constants.JOIN_KEY_PATTERNS.
# KEY_PATTERNS alias per backward compat interna a questo file.
KEY_PATTERNS: list[tuple[str, str, str]] = JOIN_KEY_PATTERNS  # type: ignore[assignment]

# ── Bridge table ──────────────────────────────────────────────────────────────
# Il dataset nel catalogo che funge da bridge table per join indiretti.
# Le sue colonne vengono lette dinamicamente dal clean_catalog.json e
# processate con KEY_PATTERNS per derivare le chiavi semantiche coperte.
BRIDGE_SLUG: str = "bdap_anagrafe_enti"


def load_source_check() -> list[dict[str, Any]]:
    """Legge source_check_results.parquet da GCS via DuckDB S3 diretto."""
    print("  Lettura source_check_results.parquet via DuckDB S3...", end=" ", flush=True)
    with gcs_connect(SOURCE_CHECK_URL) as con:
        df = con.execute(f"SELECT * FROM read_parquet('{SOURCE_CHECK_URL}')").fetchdf()
    print(f"{len(df)} righe, {len(df.columns)} colonne")
    return df.to_dict("records")


def load_clean_catalog() -> list[dict[str, Any]]:
    """Scarica clean_catalog.json da GitHub via HttpClient."""
    print("  Download clean_catalog.json...", end=" ", flush=True)
    client = HttpClient(timeout=30)
    try:
        result = client.get(CATALOG_URL)
        if not result.is_ok or result.response is None:
            raise RuntimeError(f"Failed to fetch catalog: {result.err}")
        raw = result.response.json()
        datasets: list[dict] = raw if isinstance(raw, list) else raw.get("datasets", [])
        print(f"{len(datasets)} dataset")
        return datasets
    finally:
        client.close()


# parse_columns e detect_join_keys importate da _constants.
# detect_keys alias per backward compat interna a questo file.
def detect_keys(column_names: list[str]) -> dict[str, list[str]]:
    """Matcha i nomi colonna contro i pattern di chiavi di join."""
    return detect_join_keys(None, columns=column_names)


def build_catalog_index(catalog: list[dict]) -> dict[str, dict]:
    """Costruisce indice slug → {columns, name, source} dal catalogo."""
    index: dict[str, dict] = {}
    for ds in catalog:
        slug = ds.get("slug", ds.get("name", ""))
        cols_raw = ds.get("columns", [])
        if isinstance(cols_raw, list):
            col_names = [c.get("name", str(c)) if isinstance(c, dict) else str(c) for c in cols_raw]
        elif isinstance(cols_raw, dict):
            col_names = list(cols_raw.keys())
        else:
            col_names = []
        index[slug] = {
            "slug": slug,
            "name": ds.get("name", ds.get("title", slug)),
            "source": ds.get("source", ""),
            "columns": col_names,
            "col_set": set(c.lower() for c in col_names),
        }
    return index


def derive_bridge_keys(catalog_index: dict[str, dict]) -> set[str]:
    """Deriva le chiavi semantiche coperte dalla bridge table dal catalogo.

    Cerca il dataset con slug BRIDGE_SLUG e processa le sue colonne
    con KEY_PATTERNS per ottenere le chiavi semantiche.
    """
    bridge = catalog_index.get(BRIDGE_SLUG)
    if not bridge:
        return set()
    bridge_keys: set[str] = set()
    for col in bridge["col_set"]:
        for key_name, pattern, _ in KEY_PATTERNS:
            if re.search(pattern, col):
                bridge_keys.add(key_name)
    return bridge_keys


def cross_reference(
    found_keys: dict[str, list[str]],
    catalog_index: dict[str, dict],
    bridge_semantic_keys: set[str] | None = None,
    our_cols_lower: set[str] | None = None,
) -> list[dict]:
    """Trova dataset nel catalogo che condividono almeno una chiave.

    Include match indiretti via bridge table:
    se candidate ha chiave semantica A coperta dalla bridge, e dataset Y ha
    chiave semantica B coperta dalla bridge, sono considerati joinabili
    (anche se A != B). bridge_semantic_keys viene derivato dinamicamente
    dal catalogo se non fornito.

    Restituisce lista di {slug, name, matched_keys} ordinata per match.
    """
    if bridge_semantic_keys is None:
        bridge_semantic_keys = derive_bridge_keys(catalog_index)

    matches: list[dict] = []
    if our_cols_lower is None:
        our_cols_lower = set()
        for cols in found_keys.values():
            for c in cols:
                our_cols_lower.add(c.lower())

    # Chiavi semantiche del candidate (es. {"istat_comune", "provincia"})
    semantic_keys = set(found_keys.keys())

    # Bridge: candidate ha almeno una chiave semantica coperta dalla bridge
    bridge_hit = semantic_keys & bridge_semantic_keys

    for slug, info in catalog_index.items():
        # Match diretto: stessa colonna
        direct = our_cols_lower & info["col_set"]

        # Match indiretto via bridge: candidate ha chiave semantica A coperta
        # dalla bridge, dataset ha chiave semantica B sempre coperta dalla bridge
        # (A può essere diversa da B — la bridge fa da ponte)
        # Le chiavi semantiche del dataset sono derivate da quelle catalogate
        # nel clean_catalog.json con la stessa logica.
        ds_semantic: set[str] = set()
        for col in info["col_set"]:
            for key_name, pattern, _ in KEY_PATTERNS:
                if re.search(pattern, col):
                    ds_semantic.add(key_name)
        via_bridge = bool(bridge_hit and (ds_semantic & bridge_semantic_keys) and not direct)

        common = direct | (ds_semantic if via_bridge else set())
        if common:
            tags = []
            if direct:
                tags.append("diretto")
            if via_bridge:
                tags.append("via bridge")
            matches.append(
                {
                    "slug": slug,
                    "name": info["name"],
                    "matched_keys": sorted(common),
                    "match_count": len(common),
                    "match_tags": "+".join(tags),
                    "source": info["source"],
                }
            )

    matches.sort(key=lambda m: -m["match_count"])
    return matches


def compute_joinability_score(
    found_keys: dict[str, list[str]],
    catalog_matches: list[dict],
) -> float:
    """Score 0-100: peso su chiavi geografiche + cross-reference + bridge."""
    score = 0.0

    # Peso per tipo di chiave
    key_weights = {
        "istat_comune": 30,
        "istat_regione": 20,
        "anno": 15,
        "provincia": 10,
        "codice_catastale": 15,
        "codice_ente": 10,
        "codice_scuola": 8,
        "atc": 5,
        "ateco": 5,
        "mese": 3,
        "codice_comune_anagrafe": 10,
    }

    for key_name in found_keys:
        score += key_weights.get(key_name, 5)

    # Bonus per chiavi multiple
    if len(found_keys) >= 3:
        score += 10
    elif len(found_keys) >= 2:
        score += 5

    # Bonus per cross-reference con catalogo esistente
    if catalog_matches:
        # Peso extra per match via bridge (transitivi)
        bridge_matches = sum(1 for m in catalog_matches if "bridge" in m.get("match_tags", ""))
        direct_matches = sum(1 for m in catalog_matches if "bridge" not in m.get("match_tags", ""))
        score += min(direct_matches * 3, 20)
        score += min(bridge_matches * 1, 10)  # bridge bonus

    return min(score, 100)


def item_sort_key(item: dict) -> tuple:
    """Chiave di ordinamento: score decrescente, poi numero chiavi, poi nome."""
    return (
        -item["joinability_score"],
        -len(item["found_keys"]),
        item["source_id"],
        item["item_name"],
    )


def build_json_output(
    items: list[dict],
    catalog_index: dict[str, dict],
    bridge_semantic_keys: set[str],
    stats: dict,
) -> dict:
    """Genera output JSON strutturato con i risultati dello scan."""
    # ― Item con chiavi trovate, ordinati per score
    scored_items: list[dict] = []
    for item in items:
        scored_items.append(
            {
                "source_id": item["source_id"],
                "item_name": item["item_name"],
                "intake_score": item["intake_score"],
                "joinability_score": item["joinability_score"],
                "enriched_joinability_score": item.get(
                    "enriched_joinability_score", item["joinability_score"]
                ),
                "col_count": item["col_count"],
                "keys_found": item["found_keys"],
                "matches": [
                    {
                        "slug": m["slug"],
                        "name": m["name"],
                        "matched_keys": m["matched_keys"],
                        "match_type": "direct"
                        if "diretto" in m.get("match_tags", "")
                        else "via_bridge",
                    }
                    for m in item["catalog_matches"]
                ],
                "joined_datasets": [m["slug"] for m in item["catalog_matches"]],
            }
        )
    scored_items.sort(
        key=lambda x: (
            -x["enriched_joinability_score"],
            -len(x["keys_found"]),
            x["source_id"],
            x["item_name"],
        )
    )

    # ― Statistiche chiavi aggregate
    key_counts: dict[str, int] = {}
    for item in items:
        for k in item["found_keys"]:
            key_counts[k] = key_counts.get(k, 0) + 1

    # ― Effetto bridge
    bridge_items = sum(1 for item in items if set(item["found_keys"].keys()) & bridge_semantic_keys)
    bridge_extended = sum(
        1
        for item in items
        if any("bridge" in m.get("match_tags", "") for m in item["catalog_matches"])
    )

    # ― Item ad alto intake score senza chiavi di join
    no_key_high_score = [
        {
            "source_id": item["source_id"],
            "item_name": item["item_name"],
            "intake_score": item["intake_score"],
        }
        for item in items
        if not item["found_keys"] and item["intake_score"] and item["intake_score"] >= 50
    ]
    no_key_high_score.sort(key=lambda x: -x["intake_score"])

    return {
        "generated_at": date.today().isoformat(),
        "source": "scripts/joinability_scan.py",
        "summary": {
            "total_scanned": stats["total"],
            "with_columns": stats["total"],
            "with_join_keys": stats["total_with_keys"],
            "catalog_size": stats["catalog_size"],
        },
        "bridge": {
            "slug": BRIDGE_SLUG,
            "name": catalog_index.get(BRIDGE_SLUG, {}).get("name", BRIDGE_SLUG),
            "semantic_keys": sorted(bridge_semantic_keys),
            "candidates_covered": bridge_items,
            "candidates_with_indirect": bridge_extended,
        },
        "key_statistics": {
            "total_key_types": len(key_counts),
            "keys": sorted(
                ({"key": k, "count": c} for k, c in key_counts.items()),
                key=lambda x: -x["count"],
            ),
        },
        "high_score_no_keys": no_key_high_score[:10],
        "top_items": scored_items[:50],
    }


def main() -> None:
    print("=" * 60)
    print("  Joinability Scan — source_check_results.parquet")
    print("=" * 60)
    print()

    # 1. Carica dati
    print("[1/5] Caricamento dati...")
    print()
    src_records = load_source_check()
    catalog = load_clean_catalog()
    catalog_index = build_catalog_index(catalog)

    # 2. Deriva chiavi bridge dal catalogo (dinamico, non hardcoded)
    print()
    print("[2/5] Deriva bridge keys dal catalogo...")
    bridge_semantic_keys = derive_bridge_keys(catalog_index)
    if bridge_semantic_keys:
        print(
            f"     Bridge `{BRIDGE_SLUG}` → {len(bridge_semantic_keys)} chiavi: "
            f"{sorted(bridge_semantic_keys)}"
        )
    else:
        print(f"     Bridge `{BRIDGE_SLUG}` non trovato nel catalogo — solo match diretti")
    print()

    # 3. Analisi chiavi su tutti gli item
    print(f"[3/5] Analisi chiavi su {len(src_records)} item...")

    items: list[dict] = []
    total_with_columns = 0
    total_with_keys = 0

    for record in src_records:
        columns_raw = record.get("columns")
        col_names = parse_columns(columns_raw)
        if not col_names:
            continue
        total_with_columns += 1

        # Prefer pre-computed join_keys from source_check (joinability nativa).
        # Il mapping completo {chiave: [colonne_matched]} è salvato nel parquet.
        # Fall back to detecting from columns for backward compatibility.
        join_keys_raw = record.get("join_keys")
        if join_keys_raw and isinstance(join_keys_raw, str):
            try:
                parsed = json.loads(join_keys_raw)
                if isinstance(parsed, dict):
                    found_keys = parsed  # mapping completo {key: [cols]}
                elif isinstance(parsed, list):
                    # backward compat: era solo lista nomi chiave
                    found_keys = {k: [k] for k in parsed if isinstance(k, str)}
                else:
                    found_keys = detect_keys(col_names)
            except (json.JSONDecodeError, TypeError):
                found_keys = detect_keys(col_names)
        else:
            found_keys = detect_keys(col_names)

        if found_keys:
            total_with_keys += 1

        catalog_matches = cross_reference(found_keys, catalog_index, bridge_semantic_keys)
        # Use pre-computed base score, enrich with cross-ref bonus
        base_score = record.get("joinability_score", 0) or 0
        cross_ref_bonus = min(
            len([m for m in catalog_matches if "bridge" not in m.get("match_tags", "")]) * 3, 20
        )
        cross_ref_bonus += min(
            len([m for m in catalog_matches if "bridge" in m.get("match_tags", "")]) * 1, 10
        )
        enriched_score = min(base_score + cross_ref_bonus, 100)

        items.append(
            {
                "source_id": record.get("source_id", "?"),
                "item_name": record.get("item_name", record.get("title", "?")),
                "title": record.get("title", ""),
                "intake_score": record.get("intake_score", 0) or 0,
                "granularity": record.get("granularity", ""),
                "resource_format": record.get("resource_format", ""),
                "col_count": len(col_names),
                "found_keys": found_keys,
                "catalog_matches": catalog_matches,
                "joinability_score": base_score,
                "enriched_joinability_score": enriched_score,
            }
        )

    items.sort(key=item_sort_key)

    # Statistiche
    print(f"     {total_with_columns} item con colonne sniffate")
    print(f"     {total_with_keys} item con almeno una chiave di join riconosciuta")
    print(f"     {len(items)} item in report")

    stats = {
        "total": total_with_columns,
        "total_with_keys": total_with_keys,
        "catalog_size": len(catalog),
    }

    # 4. Genera output JSON
    print()
    print("[4/5] Generazione output JSON...")
    output = build_json_output(items, catalog_index, bridge_semantic_keys, stats)

    # 5. Scrivi output
    print()
    print("[5/5] Scrittura output...")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"     Output scritto in: {OUTPUT_PATH}")
    print()

    # Riepilogo
    print("=" * 60)
    print(f"  Fatto. {total_with_keys}/{total_with_columns} item hanno chiavi di join.")
    print(f"  Vedi: {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
