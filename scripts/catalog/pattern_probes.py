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


def probe_pattern(url: str, min_bytes: int = 0, user_agent: str | None = None) -> dict[str, Any]:
    """Probe singolo URL. Non alza eccezioni: errore → available=False.

    Args:
        url: URL sentinella da verificare.
        min_bytes: se > 0, una risposta 2xx piu' corta di N byte non conta
            come disponibile. Serve per le fonti che rispondono 200 con corpo
            vuoto quando la risorsa non esiste ancora (es. MEF analisi_stat:
            200 + 0 byte per l'anno non pubblicato).
        user_agent: UA della richiesta (default: quello del probe). Serve alle
            fonti che bloccano i client generici (WAF) e dichiarano un UA nel
            proprio ``[tool.observatory]``.
    """
    client = HttpClient(timeout=TIMEOUT_SECONDS, user_agent=user_agent or USER_AGENT)
    result = client.get(url, allow_redirects=True, stream=True)
    if result.is_ok and result.response is not None:
        resp = result.response
        is_2xx = 200 <= resp.status_code < 300
        length = len(resp.content) if resp.content is not None else 0
        below_min_bytes = is_2xx and min_bytes > 0 and length < min_bytes
        outcome: dict[str, Any] = {
            "url": url,
            "available": is_2xx and not below_min_bytes,
            "http_code": str(resp.status_code),
            "content_length": length if is_2xx else None,
        }
        if below_min_bytes:
            outcome["below_min_bytes"] = True
        return outcome
    return {
        "url": url,
        "available": False,
        "http_code": "-",
        "error": str(result.err)[:120] if result.err else "unknown",
    }


def run_pattern_probes(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Esegue tutti i pattern_probes del config.

    Ogni entry: {"name": "...", "url": "...", "min_bytes": <int, opzionale>}.
    Il campo name e' opzionale.
    """
    results: list[dict[str, Any]] = []
    for entry in probes:
        url = str(entry.get("url") or "")
        if not url:
            continue
        outcome = probe_pattern(url, min_bytes=_entry_min_bytes(entry))
        if entry.get("name"):
            outcome["name"] = str(entry["name"])
        results.append(outcome)
    return results


def _entry_min_bytes(entry: dict[str, Any]) -> int:
    """``min_bytes`` dell'entry come int >= 0 (0 = nessuna soglia)."""
    raw = entry.get("min_bytes")
    if raw is None:
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


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
