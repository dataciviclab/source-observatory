"""Pattern probes — sentinel URL per rilevare nuovi contenuti upstream.

Alcune fonti non hanno catalogo enumerabile ma pubblicano file con URL
deterministici (es. OpenCivitas: ``{year}_VAR_FSC_1_{year}_csv.zip``).
Il config ``[tool.observatory]`` puo' dichiarare ``pattern_probes``: una
lista di URL sentinel da verificare ad ogni build del catalog.

Se un probe passa da non-available (4xx/5xx) a available (2xx), il
verdict operativo riceve il trigger ``new_content_available`` — segnale
che la fonte ha pubblicato qualcosa di nuovo.
"""

from __future__ import annotations

from typing import Any

from lab_connectors.http import HttpClient

USER_AGENT = "DataCivicLab-SourceObservatory/1.0 (pattern-probe)"
TIMEOUT_SECONDS = 30


def probe_pattern(url: str) -> dict[str, Any]:
    """Probe singolo URL. Non alza eccezioni: errore → available=False."""
    client = HttpClient(timeout=TIMEOUT_SECONDS, user_agent=USER_AGENT)
    result = client.get(url, allow_redirects=True, stream=True)
    if result.is_ok and result.response is not None:
        resp = result.response
        available = 200 <= resp.status_code < 300
        return {
            "url": url,
            "available": available,
            "http_code": str(resp.status_code),
            "content_length": len(resp.content) if available else None,
        }
    return {
        "url": url,
        "available": False,
        "http_code": "-",
        "error": str(result.err)[:120] if result.err else "unknown",
    }


def run_pattern_probes(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Esegue tutti i pattern_probes del config.

    Ogni entry: {"name": "...", "url": "..."}. Il campo name e' opzionale.
    """
    results: list[dict[str, Any]] = []
    for entry in probes:
        url = str(entry.get("url") or "")
        if not url:
            continue
        outcome = probe_pattern(url)
        if entry.get("name"):
            outcome["name"] = str(entry["name"])
        results.append(outcome)
    return results


def compute_new_content_trigger(
    current: list[dict[str, Any]],
    previous_catalog: dict[str, Any] | None,
) -> bool:
    """True se almeno un probe e' newly-available rispetto al catalog precedente.

    Un probe e' "newly available" se ora available=True e nel catalog
    precedente lo stesso URL era assente o available=False.
    """
    prev = {
        p.get("url"): bool(p.get("available"))
        for p in (previous_catalog or {}).get("pattern_probes") or []
    }
    for p in current:
        if p.get("available") and not prev.get(p.get("url"), False):
            return True
    return False
