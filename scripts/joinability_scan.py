#!/usr/bin/env python3
"""
joinability_scan.py — Scansione leggera della joinabilità dei candidate in source_check_results.

Legge source_check_results.parquet (da GCS pubblico), analizza la colonna `columns`
di ogni item e identifica pattern di chiavi di join note (codici ISTAT, anno, provincia,
codice ente, ecc.). Cross-referenzia col catalogo esistente (clean_catalog.json) per
mostrare quali dataset del Lab diventerebbero joinabili.

Output: observatory-results/joinability_report.md (gitignorato)
Nessuna modifica a workflow, CI o artifact SO.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import date
from typing import Any

import requests

# ── Percorsi ──────────────────────────────────────────────────────────────────

SOURCE_CHECK_URL = (
    "https://storage.googleapis.com/dataciviclab-clean/"
    "catalog_inventory/source-check/source_check_results.parquet"
)

CATALOG_URL = (
    "https://raw.githubusercontent.com/dataciviclab/"
    "dataset-incubator/main/registry/clean_catalog.json"
)

OUTPUT_REL_DIR = "observatory-results"  # gitignorato in SO

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    OUTPUT_REL_DIR,
    "joinability_report.md",
)


# ── Pattern di chiavi di join ─────────────────────────────────────────────────
# Ogni entry: (chiave_semantica, regex, descrizione)

# ── Bridge table ──────────────────────────────────────────────────────────────
# Il dataset nel catalogo che funge da bridge table per join indiretti.
# Le sue colonne vengono lette dinamicamente dal clean_catalog.json e
# processate con KEY_PATTERNS per derivare le chiavi semantiche coperte.
BRIDGE_SLUG: str = "bdap_anagrafe_enti"

KEY_PATTERNS: list[tuple[str, str, str]] = [
    ("istat_comune",
     r"(?i)(codice_istat_comune|codice_comune_istat|^codice_comune$|^pro_com$|^comune$)",
     "Codice ISTAT comune (8 digit alfanumerico)"),
    ("istat_regione",
     r"(?i)(codice_istat_regione|^codice_regione$|^codreg$|regione_istat_cod|^cod_reg$)",
     "Codice ISTAT regione"),
    ("anno",
     r"(?i)^(anno|anno_di_imposta|anno_scolastico|annoscolastico|anno_riferimento|anno_presentazione|esercizio_finanziario)$",
     "Anno / esercizio"),
    ("provincia",
     r"(?i)(sigla_provincia|^provincia$|codice_provincia|sigla_prov|^prov$)",
     "Provincia (sigla o codice)"),
    ("codice_catastale",
     r"(?i)(codice_catastale|cod_catastale|catastale)",
     "Codice catastale comune"),
    ("codice_ente",
     r"(?i)(codice_ente_ipa|^id_ente$|codice_ente_siope|codice_istituzione|codice_ente_bdap|codice_ente_ssn)",
     "Codice ente pubblico (IPA/SIOPE/BDAP/SSN)"),
    ("codice_scuola",
     r"(?i)(codice_scuola|codicescuola|codice_meccanografico|^codice_scuola$|^cod_scuola$)",
     "Codice scuola (MIM)"),
    ("atc",
     r"(?i)(^atc[1-5]$|^atc$|^atc1$|^atc2$|^atc3$|^atc4$|^atc5$)",
     "Classificazione ATC farmaceutica"),
    ("ateco",
     r"(?i)(codice_ateco|^ateco$|sezione_ateco)",
     "Classificazione ATECO attività economica"),
    ("mese",
     r"(?i)^mese$",
     "Mese (1-12)"),
    ("codice_comune_anagrafe",
     r"(?i)(^codice_comune$|^comune_istat$|^comune_codice$)",
     "Codice comune (generico, forse ISTAT)"),
]


def load_source_check() -> list[dict[str, Any]]:
    """Scarica e carica source_check_results.parquet come lista di dict."""
    import pyarrow.parquet as pq
    import io

    print(f"  Download source_check_results.parquet...", end=" ", flush=True)
    resp = requests.get(SOURCE_CHECK_URL, timeout=60)
    resp.raise_for_status()
    data = io.BytesIO(resp.content)
    table = pq.read_table(data)
    df = table.to_pandas()
    print(f"{len(df)} righe, {len(df.columns)} colonne")
    return df.to_dict("records")


def load_clean_catalog() -> list[dict[str, Any]]:
    """Scarica e carica clean_catalog.json come lista di dataset."""
    print(f"  Download clean_catalog.json...", end=" ", flush=True)
    resp = requests.get(CATALOG_URL, timeout=30)
    resp.raise_for_status()
    raw = resp.json()
    datasets: list[dict] = raw if isinstance(raw, list) else raw.get("datasets", [])
    print(f"{len(datasets)} dataset")
    return datasets


def parse_columns(columns_raw: Any) -> list[str]:
    """Parsa la colonna `columns` in una lista di nomi colonna."""
    if columns_raw is None or (isinstance(columns_raw, float) and columns_raw != columns_raw):
        return []
    if not isinstance(columns_raw, str):
        return []
    try:
        parsed = json.loads(columns_raw)
    except (json.JSONDecodeError, TypeError):
        return [str(columns_raw)]
    if isinstance(parsed, list):
        return [str(c) if not isinstance(c, dict) else str(c.get("name", "")) for c in parsed]
    if isinstance(parsed, dict):
        return list(parsed.keys())
    return [str(parsed)]


def detect_keys(column_names: list[str]) -> dict[str, list[str]]:
    """Matcha i nomi colonna contro i pattern di chiavi di join.

    Restituisce dict {nome_chiave: [colonne_matched]}.
    """
    found: dict[str, list[str]] = {}
    for key_name, pattern, _desc in KEY_PATTERNS:
        matched = [col for col in column_names if re.search(pattern, col.strip())]
        if matched:
            found[key_name] = matched
    return found


def build_catalog_index(catalog: list[dict]) -> dict[str, dict]:
    """Costruisce indice slug → {columns, name, source} dal catalogo."""
    index: dict[str, dict] = {}
    for ds in catalog:
        slug = ds.get("slug", ds.get("name", ""))
        cols_raw = ds.get("columns", [])
        if isinstance(cols_raw, list):
            col_names = [
                c.get("name", str(c)) if isinstance(c, dict) else str(c)
                for c in cols_raw
            ]
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
            matches.append({
                "slug": slug,
                "name": info["name"],
                "matched_keys": sorted(common),
                "match_count": len(common),
                "match_tags": "+".join(tags),
                "source": info["source"],
            })

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
    return (-item["joinability_score"], -len(item["found_keys"]), item["source_id"], item["item_name"])


def build_report(
    items: list[dict],
    catalog_index: dict[str, dict],
    bridge_semantic_keys: set[str],
    stats: dict,
) -> str:
    """Genera il report markdown."""
    lines: list[str] = []
    lines.append(f"# Joinability Report — {date.today().isoformat()}")
    lines.append("")
    lines.append(f"Scansione di {stats['total']} item in `source_check_results.parquet` "
                 f"con colonne sniffate. {stats['total_with_keys']} item hanno "
                 f"almeno una chiave di join riconosciuta.")
    lines.append("")
    lines.append(f"**Catalogo di riferimento**: {stats['catalog_size']} dataset "
                 f"in `clean_catalog.json`")
    lines.append("")

    # ── Tabella riepilogativa ──
    lines.append("## Top 30 item per joinability")
    lines.append("")
    lines.append("| # | Fonte | Item | Score | Chiavi trovate | Joinabile con (n) |")
    lines.append("|---|---|---|---|---|---|")

    for i, item in enumerate(items[:30], 1):
        source_id = item["source_id"]
        item_name = item["item_name"][:50]
        score = item["joinability_score"]
        keys = ", ".join(sorted(item["found_keys"].keys()))
        n_join = len(item["catalog_matches"])
        lines.append(f"| {i} | {source_id} | {item_name} | {score:.0f} | {keys} | {n_join} |")

    lines.append("")
    lines.append(f"_{len(items)} item totali con colonne sniffate_")
    lines.append("")

    # ── Per fonte ──
    lines.append("## Dettaglio per fonte")
    lines.append("")

    by_source: dict[str, list] = defaultdict(list)
    for item in items:
        by_source[item["source_id"]].append(item)

    for source_id in sorted(by_source):
        source_items = sorted(by_source[source_id], key=item_sort_key)
        total = len(source_items)
        top_keys: set = set()
        for si in source_items:
            top_keys.update(si["found_keys"].keys())

        lines.append(f"### {source_id} ({total} item)")
        lines.append("")
        lines.append(f"Chiavi trovate in questa fonte: `{'`, `'.join(sorted(top_keys))}`")
        lines.append("")

        for item in source_items[:10]:
            score = item["joinability_score"]
            keys_detail = "; ".join(
                f"{k}: {', '.join(v)}" for k, v in item["found_keys"].items()
            )
            matches = item["catalog_matches"]
            if matches:
                top3 = ", ".join(
                    f"{m['slug']} ({m.get('match_tags','diretto')})"
                    for m in matches[:3]
                )
                join_note = f"→ {top3} (+{len(matches)-3})" if len(matches) > 3 else f"→ {top3}"
            else:
                join_note = "—"

            lines.append(f"- **{item['item_name'][:55]}** (score={score:.0f})")
            lines.append(f"  - chiavi: {keys_detail}")
            lines.append(f"  - {join_note}")

        if len(source_items) > 10:
            lines.append(f"  - ... e altri {len(source_items) - 10} item")

        lines.append("")

    # ── Item senza chiavi utili ──
    no_key_items = [
        item for item in items
        if not item["found_keys"] and item["intake_score"] and item["intake_score"] >= 50
    ]
    if no_key_items:
        lines.append("## Item ad alto intake score ma senza chiavi di join riconosciute")
        lines.append("")
        lines.append("Possono comunque essere utili ma non si uniscono automaticamente "
                     "col catalogo esistente.")
        lines.append("")
        for item in sorted(no_key_items, key=lambda x: -x["intake_score"])[:10]:
            lines.append(f"- {item['source_id']}/{item['item_name'][:50]} "
                         f"(intake_score={item['intake_score']:.0f})")
        lines.append("")

    # ── Effetto bridge ──
    bridge_before = sum(1 for item in items if item["catalog_matches"])
    # Item con almeno una chiave semantica coperta dalla bridge
    bridge_items = 0
    for item in items:
        semantic_keys = set(item["found_keys"].keys())  # es. {"istat_comune", "provincia"}
        if semantic_keys & bridge_semantic_keys:
            bridge_items += 1

    # Item che ottengono match aggiuntivi VIA bridge (oltre ai diretti)
    bridge_extended = sum(
        1 for item in items
        if any("bridge" in m.get("match_tags", "") for m in item["catalog_matches"])
    )

    bridge_name = catalog_index.get(BRIDGE_SLUG, {}).get("name", BRIDGE_SLUG)

    lines.append(f"## Effetto bridge (`{BRIDGE_SLUG}`)")
    lines.append("")
    lines.append(f"La bridge table **{bridge_name}** (`{BRIDGE_SLUG}`) copre "
                 f"**{len(bridge_semantic_keys)} chiavi semantiche**: "
                 f"`{'`, `'.join(sorted(bridge_semantic_keys))}`")
    lines.append("")
    lines.append(f"- **{bridge_items}** item candidate hanno almeno una chiave coperta dalla bridge "
                 f"→ potenzialmente joinabili con tutto il catalogo via bridge")
    lines.append(f"- **{bridge_extended}** item hanno guadagnato match aggiuntivi "
                 f"grazie alla bridge (match indiretti)")
    lines.append(f"- **{bridge_before}** item avevano già match diretto con dataset esistenti")
    lines.append(f"- Match via bridge scoprono connessioni tra codici diversi "
                 f"(es. `codice_catastale` ↔ `codice_istat_comune`)")
    lines.append("")

    # ── Statistiche chiavi ──
    lines.append("## Statistiche chiavi di join")
    lines.append("")
    key_counts: dict[str, int] = defaultdict(int)
    for item in items:
        for k in item["found_keys"]:
            key_counts[k] += 1

    for key_name in sorted(key_counts, key=lambda k: -key_counts[k]):
        lines.append(f"- **{key_name}**: presente in {key_counts[key_name]} item")

    lines.append("")
    lines.append("---")
    lines.append(f"Generato da `scripts/joinability_scan.py` il {date.today().isoformat()}")

    return "\n".join(lines)


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
    print(f"[2/5] Deriva bridge keys dal catalogo...")
    bridge_semantic_keys = derive_bridge_keys(catalog_index)
    if bridge_semantic_keys:
        print(f"     Bridge `{BRIDGE_SLUG}` → {len(bridge_semantic_keys)} chiavi: "
              f"{sorted(bridge_semantic_keys)}")
    else:
        print(f"     Bridge `{BRIDGE_SLUG}` non trovato nel catalogo — "
              f"solo match diretti")
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

        found_keys = detect_keys(col_names)
        if found_keys:
            total_with_keys += 1

        catalog_matches = cross_reference(found_keys, catalog_index, bridge_semantic_keys)
        joinability_score = compute_joinability_score(found_keys, catalog_matches)

        items.append({
            "source_id": record.get("source_id", "?"),
            "item_name": record.get("item_name", record.get("title", "?")),
            "title": record.get("title", ""),
            "intake_score": record.get("intake_score", 0) or 0,
            "granularity": record.get("granularity", ""),
            "resource_format": record.get("resource_format", ""),
            "col_count": len(col_names),
            "found_keys": found_keys,
            "catalog_matches": catalog_matches,
            "joinability_score": joinability_score,
        })

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

    # 4. Genera report
    print()
    print(f"[4/5] Generazione report...")
    report = build_report(items, catalog_index, bridge_semantic_keys, stats)

    # 5. Scrivi output
    print()
    print(f"[5/5] Scrittura output...")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(report)
    print(f"     Report scritto in: {OUTPUT_PATH}")
    print()

    # Riepilogo
    print("=" * 60)
    print(f"  Fatto. {total_with_keys}/{total_with_columns} item hanno chiavi di join.")
    print(f"  Vedi: {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
