#!/usr/bin/env python3
"""
discover_portals.py — scopre portali open data PA italiani via ricerca web.

Esegue query DDG su domini .gov.it, estrae domini unici, tenta
protocol detection (CKAN, SDMX, SPARQL, HTML) e produce un Parquet.

Uso:
    python scripts/discover_portals.py
    python scripts/discover_portals.py --max-results 50 --out data/portal_scout/discovered_portals.parquet
    python scripts/discover_portals.py --no-probe    # solo raccolta URL, senza detection
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collectors.base import observatory_get

OUT_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "portal_scout" / "discovered_portals.parquet"

# Query generiche (sempre usate)
SEARCH_QUERIES_BASE = [
    '"open data" site:gov.it',
    '"opendata" site:gov.it',
    '"dati aperti" site:gov.it',
    '"catalogo dati" site:gov.it',
    '"API" "open data" ministero site:gov.it',
]

# Query specifiche per protocollo
SEARCH_QUERIES_BY_PROTOCOL: dict[str, list[str]] = {
    "ckan":   ['"CKAN" "open data" site:gov.it'],
    "sdmx":   ['"SDMX" site:gov.it'],
    "sparql": ['"SPARQL" endpoint site:gov.it', '"linked open data" site:gov.it'],
}

# Endpoint probe per protocol detection
PROBE_PATHS = {
    "ckan":   ["/api/3/action/package_list", "/api/action/package_list"],
    "sdmx":   ["/SDMXWS/rest/dataflow", "/sdmx/rest/dataflow", "/rest/dataflow"],
    "sparql": ["/sparql", "/sparql/query", "/endpoint/sparql", "/lod/sparql", "/opendata/sparql"],
}

SKIP_DOMAINS = {
    "www.gov.it", "www.governo.it", "www.italia.it", "wikipedia.org",
    "github.com", "medium.com", "agid.gov.it", "developers.italia.it",
    "docs.italia.it", "forum.italia.it", "innovazione.gov.it",
    "agea.gov.it",  # falso positivo SDMX — redirect a SPA React
}

# Domini già noti nel registry — usati per marcare i candidati come nuovi vs noti
KNOWN_REGISTRY_DOMAINS = {
    "esploradati.istat.it",
    "dati.anticorruzione.it",
    "serviziweb2.inps.it",
    "bdap-opendata.rgs.mef.gov.it",
    "www.dati.salute.gov.it",
    "dati.inail.it",
    "dati.istruzione.it",
    "dati.camera.it",
    "dati.isprambiente.it",
    "dati.consip.it",
    "dati.lavoro.gov.it",
    "dati-ustat.mur.gov.it",
    "opencoesione.gov.it",
    "openbdap.rgs.mef.gov.it",
}

TIMEOUT = 8


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_ddg(queries: list[str], max_per_query: int) -> list[dict]:
    from ddgs import DDGS  # type: ignore[import-not-found]
    results = []
    with DDGS() as ddgs:
        for query in queries:
            try:
                hits = list(ddgs.text(query, max_results=max_per_query))
                results.extend(hits)
                time.sleep(1.5)  # rate limit
            except Exception as exc:
                print(f"  [warn] query '{query}': {exc}", file=sys.stderr)
    return results


def extract_domains(results: list[dict]) -> dict[str, set[str]]:
    """Ritorna {domain: set_of_source_queries}."""
    domains: dict[str, set[str]] = {}
    for r in results:
        url = r.get("href") or r.get("url") or ""
        query = r.get("query", "")
        if not url:
            continue
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
        if not domain:
            continue
        if any(skip in domain for skip in SKIP_DOMAINS):
            continue
        # Tieni solo domini che sembrano portali PA (.gov.it, .regione.*, .comune.*, .it)
        if not domain.endswith(".gov.it"):
            continue
        if domain not in domains:
            domains[domain] = set()
        domains[domain].add(query or url)
    return domains


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------

def detect_protocol(domain: str, probe_paths: dict | None = None) -> tuple[str, str | None]:
    """Torna (protocol, working_url) o ('html', None)."""
    base = f"https://{domain}"
    for protocol, paths in (probe_paths or PROBE_PATHS).items():
        for path in paths:
            url = base + path
            try:
                r = observatory_get(url, timeout=TIMEOUT)
                if r.status_code == 200:
                    ct = r.headers.get("content-type", "").lower()
                    if protocol == "ckan" and ("json" in ct or r.text.strip().startswith("{")):
                        try:
                            data = r.json()
                            if isinstance(data, dict) and "result" in data:
                                return "ckan", url
                        except Exception:
                            pass
                    elif protocol == "sdmx":
                        text = r.text[:5000]
                        # Richiede namespace SDMX reale — scarta SPA/HTML che iniziano con <
                        if "sdmx.org" in text and text.strip().startswith("<") and "<!DOCTYPE" not in text[:100] and "<html" not in text[:200]:
                            return "sdmx", url
                    elif protocol == "sparql" and ("json" in ct or "xml" in ct or "sparql" in ct):
                        return "sparql", url
            except Exception:
                pass
    return "html", None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scopre portali open data PA via ricerca web.")
    p.add_argument("--max-results", type=int, default=20, help="Risultati max per query DDG (default: 20).")
    p.add_argument("--no-probe", action="store_true", help="Salta protocol detection.")
    p.add_argument("--protocols", nargs="+", choices=["ckan", "sdmx", "sparql"],
                   help="Filtra per protocollo: usa solo query e probe mirati (es. --protocols sdmx ckan).")
    p.add_argument("--only-matched", action="store_true",
                   help="Output solo portali dove il probe ha confermato il protocollo (esclude html).")
    p.add_argument("--out", type=Path, default=OUT_DEFAULT, help="Path parquet output.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Seleziona query in base ai protocolli richiesti
    protocols = set(args.protocols) if args.protocols else set(PROBE_PATHS.keys())
    queries = list(SEARCH_QUERIES_BASE)
    for proto in sorted(protocols):
        queries.extend(SEARCH_QUERIES_BY_PROTOCOL.get(proto, []))

    # Limita i probe ai protocolli richiesti
    active_probe_paths = {k: v for k, v in PROBE_PATHS.items() if k in protocols}

    print(f"Ricerca su {len(queries)} query DDG (max {args.max_results} risultati ciascuna)"
          + (f" — protocolli: {', '.join(sorted(protocols))}" if args.protocols else "") + "...")
    results = search_ddg(queries, args.max_results)
    print(f"  {len(results)} risultati grezzi")

    domains = extract_domains(results)
    print(f"  {len(domains)} domini unici estratti")

    def _probe_domain(domain: str, sources: set[str]) -> dict:
        if args.no_probe:
            protocol, probe_url = "unknown", None
        else:
            protocol, probe_url = detect_protocol(domain, active_probe_paths)
            print(f"  probe {domain} ... {protocol}", flush=True)
        in_registry = domain in KNOWN_REGISTRY_DOMAINS or any(
            domain.endswith("." + kd) or kd.endswith("." + domain)
            for kd in KNOWN_REGISTRY_DOMAINS
        )
        return {
            "domain": domain,
            "protocol": protocol,
            "probe_url": probe_url or "",
            "base_url": f"https://{domain}",
            "in_registry": "yes" if in_registry else "no",
            "source_queries": " | ".join(sorted(sources)),
        }

    rows = []
    workers = 1 if args.no_probe else 10
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_probe_domain, d, s): d for d, s in sorted(domains.items())}
        for future in as_completed(futures):
            rows.append(future.result())

    import json
    import pandas as pd
    from datetime import datetime, timezone

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["domain", "protocol", "probe_url", "base_url", "in_registry", "source_queries"])

    if args.only_matched:
        confirmed = args.protocols if args.protocols else list(PROBE_PATHS.keys())
        df = df[df["protocol"].isin(confirmed)]
        print(f"  filtrati a {len(df)} portali con protocollo confermato ({', '.join(confirmed)})")

    df.to_parquet(args.out, index=False)

    new_candidates = df[df["in_registry"] == "no"]
    print(f"  di cui {len(new_candidates)} nuovi candidati (non nel registry)")

    # JSON summary per ACB e lettura rapida
    confirmed_protocols = ["ckan", "sdmx", "sparql"]
    new_confirmed = new_candidates[new_candidates["protocol"].isin(confirmed_protocols)]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_portals": len(df),
        "new_candidates": len(new_candidates),
        "new_confirmed_protocol": len(new_confirmed),
        "by_protocol": df["protocol"].value_counts().to_dict(),
        "top_candidates": [
            {"domain": r["domain"], "protocol": r["protocol"], "probe_url": r["probe_url"]}
            for _, r in new_confirmed.iterrows()
        ],
    }
    summary_path = args.out.with_name("discovered_portals_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Summary scritto in {summary_path}")

    print(f"\nScritti {len(rows)} portali in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
