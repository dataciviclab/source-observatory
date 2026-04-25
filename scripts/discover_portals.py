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
import json
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collectors.base import observatory_get

OUT_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "portal_scout" / "discovered_portals.parquet"

# Query generiche (sempre usate) — orientate a portali nazionali con dati comunali
SEARCH_QUERIES_BASE = [
    '"open data" "comuni" site:gov.it',
    '"dati comunali" "ministero" site:gov.it',
    '"codice comune" dataset site:gov.it',
    '"API" "open data" ministero site:gov.it',
]

# Query mirate .it — pescano portali CKAN/SDMX regionali/utility con API strutturata
SEARCH_QUERIES_IT = [
    '"api/3/action" "open data" site:.it',
    '"CKAN" "dati aperti" site:.it',
    '"SDMX" "dataflow" "open data" site:.it',
    '"SPARQL" endpoint "dati aperti" site:.it',
]

# Query specifiche per protocollo
SEARCH_QUERIES_BY_PROTOCOL: dict[str, list[str]] = {
    "ckan":   ['"CKAN" "comuni" site:gov.it', '"CKAN" "open data" ministero site:gov.it'],
    "sdmx":   ['"SDMX" "dataflow" site:gov.it', '"SDMX" ISTAT site:gov.it'],
    "sparql": ['"SPARQL" endpoint "linked data" site:gov.it', '"SPARQL" "dati.gov.it"'],
}

# Pattern che identificano portali open data istituzionali su .it generico
IT_OPENDATA_PATTERNS = [
    "opendata.", "open-data.", "dati.", "portale-dati.", "datiaperiti.",
    ".comune.", ".regione.", ".provincia.", ".cm.",  # enti locali con portale dati
]

# Endpoint probe per protocol detection
PROBE_PATHS = {
    "ckan": [
        "/api/3/action/package_list",
        "/api/action/package_list",
        # Non-standard CKAN paths from known PA portals
        "/SpodCkanApi/api/3/action/package_list",
        "/odapi/api/3/action/package_list",
    ],
    "sdmx":   ["/SDMXWS/rest/dataflow", "/sdmx/rest/dataflow", "/rest/dataflow"],
    "sparql": [
        "/sparql",
        "/sparql/query",
        "/endpoint/sparql",
        "/lod/sparql",
        "/opendata/sparql",
        # Extra paths from known PA SPARQL endpoints
        "/api/sparql",
        "/api/endpoint/sparql",
        "/sparql/default",
        "/data/sparql",
    ],
}

SKIP_DOMAINS = {
    "www.gov.it", "www.governo.it", "www.italia.it", "wikipedia.org",
    "github.com", "medium.com", "agid.gov.it", "developers.italia.it",
    "docs.italia.it", "forum.italia.it", "innovazione.gov.it",
    "agea.gov.it",  # falso positivo SDMX — redirect a SPA React
}

# Pattern da scartare sempre (siti non-dati, falsi positivi)
SKIP_DOMAIN_PATTERNS = [
    "città metropolitana",
    "artbonus.",
    ".camcom.",  # camere di commercio locali — dati frammentati
]

# Portali nazionali tier-1 da includere sempre nel probe, indipendentemente dalla DDG.
# Derivati dinamicamente da sources_registry.yaml.
TIER1_DOMAINS: dict[str, str] = {}
# Domini già noti nel registry — usati per marcare i candidati come nuovi vs noti.
KNOWN_REGISTRY_DOMAINS: set[str] = set()

# ---------------------------------------------------------------------------
# Registry sync
# ---------------------------------------------------------------------------

def _sync_from_registry(registry_path: Path | None = None) -> None:
    """Popola TIER1_DOMAINS e KNOWN_REGISTRY_DOMAINS dal sources_registry.yaml."""
    global TIER1_DOMAINS, KNOWN_REGISTRY_DOMAINS
    if registry_path is None:
        registry_path = Path(__file__).resolve().parents[1] / "data" / "radar" / "sources_registry.yaml"

    if not registry_path.exists():
        return

    import yaml
    try:
        with open(registry_path, encoding="utf-8") as f:
            registry = yaml.safe_load(f)
    except Exception:
        return

    tier1: dict[str, str] = {}
    known: set[str] = set()

    for source_id, meta in (registry or {}).items():
        base_url = meta.get("base_url", "")
        protocol = meta.get("protocol", "")
        if base_url and protocol:
            # Estrai dominio dalla base_url
            try:
                from urllib.parse import urlparse
                parsed = urlparse(base_url)
                domain = parsed.netloc.lower().lstrip("www.")
                if domain:
                    known.add(domain)
                    # Solo i catalog con protocollo noto vanno in tier1
                    if protocol in ("ckan", "sdmx", "sparql"):
                        tier1[domain] = protocol
            except Exception:
                pass

    TIER1_DOMAINS = tier1
    KNOWN_REGISTRY_DOMAINS = known


_sync_from_registry()

# Probe aggressivo: se un host non risponde, non vogliamo bloccare il run.
PROBE_TIMEOUT_SECONDS = (3, 5)


# ---------------------------------------------------------------------------
# Protocol detection helpers
# ---------------------------------------------------------------------------

def _is_sdmx_xml(text: str) -> bool:
    """Validazione strutturale: questo testo è XML SDMX, non HTML o altro."""
    if not text.strip().startswith("<"):
        return False
    if "<!DOCTYPE" in text[:100] or "<html" in text[:200]:
        return False
    # SDMX namespace o prefisso nel root element
    return "sdmx.org" in text or (
        text.lstrip().startswith("<") and ":" in text[:500] and "message" in text[:1000].lower()
    )


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
    """Ritorna {domain: set_of_source_queries}. Salva path DDG per CKAN path-based probe."""
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
        if any(pat in domain for pat in SKIP_DOMAIN_PATTERNS):
            continue
        # Accetta .gov.it sempre; accetta .it generico solo se il dominio
        # ha pattern che indicano un portale open data istituzionale
        if domain.endswith(".gov.it"):
            pass
        elif domain.endswith(".it") and any(pat in domain for pat in IT_OPENDATA_PATTERNS):
            pass
        else:
            continue
        if domain not in domains:
            domains[domain] = set()
        domains[domain].add(query or url)
        # Salva il path DDG per probe CKAN path-based (thread-safe)
        if parsed.path and parsed.path != "/":
            with _DDG_PATHS_LOCK:
                _DDG_PATHS.setdefault(domain, set()).add(parsed.path)
    return domains


# Path DDG per probe CKAN path-based — protetto da lock per thread-safety
_DDG_PATHS: dict[str, set[str]] = {}
_DDG_PATHS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------

def _probe_ckan(base: str, extra_prefixes: list[str] | None = None) -> str | None:
    """Torna l'URL funzionante CKAN o None. Prova path standard + path-based da DDG."""
    suffixes = PROBE_PATHS["ckan"]
    prefixes = [""] + (extra_prefixes or [])
    for prefix in prefixes:
        for suffix in suffixes:
            url = base + prefix + suffix
            try:
                r = observatory_get(url, timeout=PROBE_TIMEOUT_SECONDS)
                if r.status_code == 200:
                    ct = r.headers.get("content-type", "").lower()
                    if "json" in ct or r.text.strip().startswith("{"):
                        data = r.json()
                        if isinstance(data, dict) and "result" in data:
                            return url
            except Exception:
                pass
    return None


def detect_protocol(domain: str, probe_paths: dict | None = None) -> tuple[str, str | None]:
    """Torna (protocol, working_url) o ('html', None)."""
    base = f"https://{domain}"

    # CKAN: probe standard + path-based da URL DDG (es. /opendata, /catalogo)
    with _DDG_PATHS_LOCK:
        ddg_paths = _DDG_PATHS.get(domain, set())
    ckan_prefixes = sorted({
        "/" + p.strip("/").split("/")[0]
        for p in ddg_paths
        if p.strip("/")
    })
    if "ckan" in (probe_paths or PROBE_PATHS):
        url = _probe_ckan(base, ckan_prefixes)
        if url:
            return "ckan", url

    # SDMX e SPARQL: probe standard
    for protocol, paths in (probe_paths or PROBE_PATHS).items():
        if protocol == "ckan":
            continue
        for path in paths:
            url = base + path
            try:
                r = observatory_get(url, timeout=PROBE_TIMEOUT_SECONDS)
                if r.status_code == 200:
                    ct = r.headers.get("content-type", "").lower()
                    if protocol == "sdmx":
                        text = r.text[:5000]
                        if _is_sdmx_xml(text):
                            return "sdmx", url
                    elif protocol == "sparql" and ("json" in ct or "xml" in ct or "sparql" in ct):
                        return "sparql", url
            except Exception:
                pass
    return "html", None


def _build_summary_artifacts(df, scouted_at: str) -> tuple[dict, list[str]]:
    """Build JSON summary payload and markdown shortlist from the discovery table."""
    known = df[df["in_registry"] == "yes"]
    new_candidates = df[df["in_registry"] == "no"]
    confirmed_protocols = ["ckan", "sdmx", "sparql"]
    new_confirmed = new_candidates[new_candidates["protocol"].isin(confirmed_protocols)]
    known_confirmed = known[known["protocol"].isin(confirmed_protocols)]

    summary = {
        "generated_at": scouted_at,
        "total_portals": len(df),
        "new_candidates": len(new_candidates),
        "new_confirmed_protocol": len(new_confirmed),
        "known_registry_seen": len(known),
        "by_protocol": df["protocol"].value_counts().to_dict(),
        "new_structured": [
            {"domain": r["domain"], "protocol": r["protocol"], "probe_url": r["probe_url"]}
            for _, r in new_confirmed.iterrows()
        ],
        "known_registry_healthcheck": [
            {"domain": r["domain"], "protocol": r["protocol"], "status": "seen"}
            for _, r in known_confirmed.iterrows()
        ],
    }

    shortlist_lines = [
        "# Portal Scout — Shortlist",
        f"\n_Generato: {summary['generated_at']}_\n",
        "## Nuovi candidati strutturati",
        "",
    ]
    if new_confirmed.empty:
        shortlist_lines.append("_Nessun nuovo candidato con protocollo confermato._")
    else:
        for _, r in new_confirmed.iterrows():
            shortlist_lines.append(f"- **{r['domain']}** — {r['protocol'].upper()}")
            shortlist_lines.append(f"  - Probe: `{r['probe_url']}`")
            shortlist_lines.append("  - Next: portal-scout approfondito + proposta registry")

    shortlist_lines += [
        "",
        "## Registry esistente — visti in questo run",
        "",
    ]
    if known_confirmed.empty:
        shortlist_lines.append("_Nessun portale noto rilevato._")
    else:
        for _, r in known_confirmed.iterrows():
            shortlist_lines.append(f"- **{r['domain']}** — {r['protocol'].upper()} ✓ già nel registry")

    shortlist_lines += [
        "",
        "## Portali HTML (non strutturati)",
        "",
        f"_{len(df[df['protocol'] == 'html'])} domini classificati HTML — nessuna API strutturata rilevata._",
    ]

    return summary, shortlist_lines


def _write_summary_artifacts(df, out_path: Path, scouted_at: str) -> tuple[Path, Path]:
    summary, shortlist_lines = _build_summary_artifacts(df, scouted_at)
    summary_path = out_path.with_name("discovered_portals_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    shortlist_path = out_path.with_name("portal_scout_shortlist.md")
    shortlist_path.write_text("\n".join(shortlist_lines) + "\n", encoding="utf-8")
    return summary_path, shortlist_path


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
    p.add_argument(
        "--refresh-summary",
        action="store_true",
        help="Rigenera summary e shortlist da un parquet già esistente in --out.",
    )
    p.add_argument("--out", type=Path, default=OUT_DEFAULT, help="Path parquet output.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.refresh_summary:
        import pandas as pd
        from datetime import datetime, timezone

        df = pd.read_parquet(args.out)
        summary_path, shortlist_path = _write_summary_artifacts(
            df, args.out, datetime.now(timezone.utc).isoformat()
        )
        print(f"Shortlist scritta in {shortlist_path}")
        print(f"Summary scritto in {summary_path}")
        return 0

    # Seleziona query in base ai protocolli richiesti
    protocols = set(args.protocols) if args.protocols else set(PROBE_PATHS.keys())
    queries = list(SEARCH_QUERIES_BASE) + list(SEARCH_QUERIES_IT)
    for proto in sorted(protocols):
        queries.extend(SEARCH_QUERIES_BY_PROTOCOL.get(proto, []))

    # Limita i probe ai protocolli richiesti
    active_probe_paths = {k: v for k, v in PROBE_PATHS.items() if k in protocols}

    print(f"Ricerca su {len(queries)} query DDG (max {args.max_results} risultati ciascuna)"
          + (f" — protocolli: {', '.join(sorted(protocols))}" if args.protocols else "") + "...")
    results = search_ddg(queries, args.max_results)
    print(f"  {len(results)} risultati grezzi")

    domains = extract_domains(results)
    # Aggiungi sempre i portali nazionali tier-1
    for tier1_domain in TIER1_DOMAINS:
        if tier1_domain not in domains:
            domains[tier1_domain] = {"tier1-allowlist"}
    print(f"  {len(domains)} domini unici estratti (inclusi {len(TIER1_DOMAINS)} tier-1)")

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

    summary_path, shortlist_path = _write_summary_artifacts(
        df, args.out, datetime.now(timezone.utc).isoformat()
    )
    print(f"Shortlist scritta in {shortlist_path}")
    print(f"Summary scritto in {summary_path}")

    print(f"\nScritti {len(rows)} portali in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
