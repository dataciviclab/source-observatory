from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .base import USER_AGENT, CollectorResult, inventory_cfg, strip_query

logger = logging.getLogger(__name__)

# Default storici: invariati per le fonti che non dichiarano override.
DEFAULT_SEARCH_PAGE_SIZE = 1000
DEFAULT_SEARCH_TIMEOUT = 60
# None => nessun dimezzamento: si usa sempre il page size configurato, come
# prima dell'introduzione dell'adattamento. Il dimezzamento è opt-in per fonte.
DEFAULT_SEARCH_MIN_PAGE_SIZE: int | None = None

# Dopo quanti successi consecutivi si prova a risalire di page size, e quante
# volte una dimensione che ha già fallito può essere riprovata.
_RECOVER_AFTER_SUCCESSES = 3
_MAX_FAILURES_PER_SIZE = 2

CKAN_ACTION_NAMES = {
    "package_list",
    "package_search",
    "package_show",
    "current_package_list_with_resources",
}


def _ckan_api_base(url: str) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path
    if "/api/3/action/" in path:
        root = path[: path.index("/api/3/action/")]
        return f"{parsed.scheme}://{parsed.netloc}{root}/api/3/action"
    # endpoint non-standard (es. INPS /odapi): usa il path fino all'ultima action nota
    for action in (
        "package_list",
        "package_search",
        "package_show",
        "current_package_list_with_resources",
    ):
        if f"/{action}" in path:
            root = path[: path.index(f"/{action}")]
            return f"{parsed.scheme}://{parsed.netloc}{root}"
    # fallback: usa host + path senza query
    root = path.rstrip("/").rsplit("/", 1)[0] if "/" in path.rstrip("/") else path
    return f"{parsed.scheme}://{parsed.netloc}{root}"


def ckan_action_endpoint(base_url: str, action: str) -> str:
    endpoint = strip_query(base_url)
    if endpoint.endswith("/"):
        endpoint = endpoint[:-1]
    if endpoint.endswith(action):
        return endpoint
    if "/api/3/action/" in endpoint:
        root = endpoint.rsplit("/", 1)[0]
        return f"{root}/{action}"
    last_segment = endpoint.rsplit("/", 1)[-1]
    if last_segment in CKAN_ACTION_NAMES:
        root = endpoint.rsplit("/", 1)[0]
        return f"{root}/{action}"
    # Nessun path API rilevato — aggiunge il path standard CKAN
    return f"{endpoint}/api/3/action/{action}"


def ckan_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    """GET JSON da un'API CKAN.

    Args:
        url: Endpoint URL (es. ``/api/3/action/package_show``).
        client: Opzionale, ``HttpClient`` riusabile per connection pooling.
            Se non fornito, ne crea uno nuovo con ``timeout``.
        **kwargs: Passati a ``HttpClient.get()``; ``timeout`` e ``headers``
            vengono estratti prima di passarli.

    Nota: ``HttpClient.get()`` non accetta un timeout per-richiesta (usa quello
    di costruzione). Se il client fornito ha un timeout diverso da quello
    richiesto, viene costruito un client dedicato: senza questo, il timeout
    configurato nel registry veniva ignorato in silenzio.
    """
    from lab_connectors.http import HttpClient

    client: HttpClient | None = kwargs.pop("client", None)
    timeout = kwargs.pop("timeout", 60)
    headers = kwargs.pop("headers", None)

    if client is not None and getattr(client, "timeout", timeout) != timeout:
        client = HttpClient(timeout=timeout, user_agent=USER_AGENT)
    if client is None:
        client = HttpClient(timeout=timeout, user_agent=USER_AGENT)

    result = client.get(url, headers=headers or {}, **kwargs)
    if not result.is_ok or result.response is None:
        raise result.err if result.err else RuntimeError(f"GET failed for {url}")
    response = result.response
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        preview = response.text[:200].replace("\n", " ").strip()
        raise ValueError(
            "CKAN API returned non-JSON content "
            f"(status={response.status_code}, content_type={content_type or 'unknown'}, "
            f"preview={preview!r})"
        )
    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:200].replace("\n", " ").strip()
        raise ValueError(
            "CKAN API returned invalid JSON "
            f"(status={response.status_code}, content_type={content_type or 'unknown'}, "
            f"preview={preview!r})"
        ) from exc


def force_https(url: str | None, allowed_host: str | None = None) -> str | None:
    """Upgrade ``http://`` a ``https://``.

    Non è un default globale: un portale http-only si romperebbe. Si attiva
    per fonte con ``inventory.force_https: true`` quando l'endpoint in chiaro
    è noto per essere morto (es. OpenBDAP: ``http://`` va in timeout,
    ``https://`` risponde in <1s).

    Se ``allowed_host`` è passato, riscrive solo gli URL di quell'host: un
    resource esterno in http-only non viene toccato.
    """
    if not url:
        return url
    if not url.lower().startswith("http://"):
        return url
    if allowed_host:
        from urllib.parse import urlsplit

        if (urlsplit(url).hostname or "").lower() != allowed_host.lower():
            return url
    return "https://" + url[len("http://") :]


def _resource_format(item: dict) -> str | None:
    resources = item.get("resources") or []
    if not resources:
        return None
    formats: list[str] = []
    for r in resources:
        fmt = str(r.get("format") or "").strip().lower()
        if fmt:
            formats.append(fmt)
    if not formats:
        return None
    unique = list(dict.fromkeys(formats))
    return ",".join(unique)


def _resource_first_url(item: dict) -> str | None:
    """Return the URL of the first resource with a valid url field."""
    resources = item.get("resources") or []
    for r in resources:
        url = r.get("url")
        if url and isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _landing_page(item: dict) -> str | None:
    """Return the dataset landing page URL (CKAN 'url' field or first resource landing)."""
    # CKAN standard: 'url' is the dataset's own landing page (not a resource)
    url = item.get("url")
    if url and isinstance(url, str) and url.strip():
        return url.strip()
    # Fallback: use first resource with a valid url as de-facto landing
    return _resource_first_url(item)


def _url_shape_score(url: str) -> int:
    """Tie-breaker: il format dichiarato dalle fonti a volte mente.

    OpenBDAP etichetta come "CSV" anche il resource che punta a un PDF, e
    siccome arriva prima vinceva il tie-break sul solo ``format_score``.
    Qui si guarda la forma reale dell'URL.
    """
    low = url.lower().strip()
    if "/datastore/dump/" in low or low.endswith(".csv") or ".csv?" in low:
        return 3
    if low.endswith((".xls", ".xlsx", ".ods")):
        return 1
    if low.endswith(".pdf"):
        return -5
    return 0


def _best_resource_url(item: dict) -> str | None:
    """Return the URL of the resource with the most pipeline-friendly format.

    Iterates all resources, scores each by format, returns the URL
    of the highest-scoring resource.  When two resources tie for
    the same score, the first one wins (stable sort).

    This fixes ANAC's issue: metadata says 'csv,json,ttl' but the
    first resource URL pointed to TTL because resources weren't
    ordered by format quality.
    """
    resources = item.get("resources") or []
    if not resources:
        return None

    best_url: str | None = None
    best_score = -(10**6)

    for r in resources:
        url = r.get("url")
        if not url or not isinstance(url, str) or not url.strip():
            continue
        fmt = r.get("format") or ""
        from scripts.engine.formats import format_score

        score = format_score(fmt) * 100 + _url_shape_score(url)
        if score > best_score:
            best_score = score
            best_url = url.strip()

    return best_url


def _distribution_url(item: dict) -> str | None:
    """Return the primary download URL for this dataset.

    Picks the resource with the most pipeline-friendly format
    (CSV > JSON > XML > ...) rather than blindly taking the first.

    Fallback: first resource with a URL if no resource has a
    recognizable format.
    """
    best = _best_resource_url(item)
    if best:
        return best
    return _resource_first_url(item)


def _has_datastore_active(item: dict) -> bool:
    resources = item.get("resources") or []
    return any(str(r.get("datastore_active") or "").lower() == "true" for r in resources)


def _resource_count(item: dict) -> int:
    return len(item.get("resources") or [])


def _resources_size_bytes(item: dict) -> int | None:
    """Somma delle dimensioni dichiarate nei resource (``size`` in byte).

    Molte fonti non popolano ``size``: in quel caso torna ``None`` invece di 0,
    così il triage distingue "non dichiarato" da "vuoto". Un ``size: 0``
    esplicito è invece un valore dichiarato e contribuisce come zero.
    """
    total = 0
    found = False
    for r in item.get("resources") or []:
        raw = str(r["size"]).strip() if r.get("size") is not None else ""
        if not raw.isdigit():
            continue
        total += int(raw)
        found = True
    return total if found else None


def extract_ckan_inventory_row(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    item: dict[str, Any],
    endpoint: str,
    ordinal: int,
    inventory_method: str,
) -> dict[str, Any]:
    organization = (item.get("organization") or {}).get("title") or (
        item.get("organization") or {}
    ).get("name")
    if not organization:
        organization = item.get("author") or item.get("maintainer")
    tag_items = item.get("tags") or []
    tags: list[str] = []
    for tag_item in tag_items:
        if isinstance(tag_item, dict):
            tag_value = tag_item.get("display_name") or tag_item.get("name")
        elif isinstance(tag_item, str):
            tag_value = tag_item.strip()
        else:
            tag_value = None
        if tag_value:
            tags.append(tag_value)
    notes = (item.get("notes") or "").strip()

    # Estrae extras (hvd_category, ecc.)
    extras_raw = item.get("extras") or []
    extras: dict[str, str] = {}
    for e in extras_raw:
        if isinstance(e, dict) and "key" in e and "value" in e:
            extras[e["key"]] = str(e["value"])

    landing_page = _landing_page(item)
    distribution_url = _distribution_url(item)
    if inventory_cfg(source_cfg).get("force_https"):
        # Solo l'host della fonte: un resource esterno in http-only non va toccato.
        from urllib.parse import urlsplit

        allowed_host = urlsplit(str(source_cfg.get("base_url") or "")).hostname
        landing_page = force_https(landing_page, allowed_host)
        distribution_url = force_https(distribution_url, allowed_host)

    return {
        "captured_at": captured_at,
        "source_id": source_id,
        "source_kind": source_cfg.get("source_kind"),
        "protocol": source_cfg.get("protocol"),
        "inventory_method": inventory_method,
        "item_kind": "dataset",
        "item_id": item.get("id") or item.get("name"),
        "item_name": item.get("name") or item.get("id"),
        "item_slug": item.get("name") or None,
        "title": item.get("title"),
        "organization": organization,
        "tags": ", ".join(tags) if tags else None,
        "notes_excerpt": notes[:300] if notes else None,
        "source_url": endpoint,
        "api_base_url": _ckan_api_base(source_cfg.get("base_url") or endpoint),
        "ordinal": ordinal,
        "format": _resource_format(item),
        "landing_page": landing_page,
        "distribution_url": distribution_url,
        "datastore_active": _has_datastore_active(item),
        "resource_count": _resource_count(item),
        # Somma dei size dichiarati: utile per il triage dei cataloghi enormi.
        # None = dimensione non dichiarata dalla fonte (non "zero byte").
        "download_size_bytes": _resources_size_bytes(item),
        # Data di creazione/modifica lato fonte (CKAN metadata_created/modified)
        "issued": item.get("metadata_created") or None,
        "modified": item.get("metadata_modified") or None,
        # Licenza (es. cc-by-4.0, cc-zero, other-open)
        "license_id": item.get("license_id"),
        "license_title": item.get("license_title"),
        # HVD category (es. http://data.europa.eu/bna/c_ac64a52d)
        "hvd_category": extras.get("hvd_category", ""),
    }


def _ckan_search_params(
    source_cfg: dict[str, Any], *, page_size: int, start: int
) -> dict[str, Any]:
    """Build package_search params, optionally adding fq from inventory config."""
    inv = source_cfg.get("inventory") or {}
    params: dict[str, Any] = {"rows": page_size, "start": start}
    fq = inv.get("fq")
    if fq:
        params["fq"] = fq
    return params


def _is_transient_error(exc: BaseException) -> bool:
    """True per errori su cui ha senso riprovare (timeout, connessione, 5xx).

    ``HttpClient`` fa già retry sui transitori: qui serve solo per decidere se
    vale la pena ridurre la pagina. Un 4xx o un JSON invalido non migliorano
    con una pagina più piccola.
    """
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name:
        return True
    try:
        import requests
    except ImportError:  # pragma: no cover — requests è dipendenza di lab-connectors
        return False
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return bool(status and status >= 500)
    return False


class _PageSizer:
    """Adatta il page size di ``package_search`` con un budget di tentativi finito.

    - se ``min_size == ceiling`` (default) non adatta nulla: un tentativo, come
      prima dell'introduzione dell'adattamento;
    - su errore transitorio dimezza, fino a ``min_size``;
    - dopo ``_RECOVER_AFTER_SUCCESSES`` successi consecutivi prova a risalire,
      senza riprovare una dimensione fallita più di ``_MAX_FAILURES_PER_SIZE``
      volte.

    Il costo massimo è quindi ``2 * numero_dimezzamenti`` timeout per pagina.
    """

    def __init__(self, ceiling: int, min_size: int | None) -> None:
        self.ceiling = max(1, ceiling)
        self.min_size = max(1, min(min_size or ceiling, ceiling))
        self.current = self.ceiling
        self.adaptive = self.min_size < self.ceiling
        self.failures: dict[int, int] = {}
        self._successes = 0

    def on_success(self) -> None:
        self._successes += 1
        if not self.adaptive or self.current >= self.ceiling:
            return
        if self._successes < _RECOVER_AFTER_SUCCESSES:
            return
        nxt = min(self.ceiling, self.current * 2)
        if self.failures.get(nxt, 0) < _MAX_FAILURES_PER_SIZE:
            self.current = nxt
            self._successes = 0

    def on_transient_failure(self) -> bool:
        """True se conviene ritentare (con una pagina più piccola, se possibile)."""
        if not self.adaptive:
            return False
        self._successes = 0
        self.failures[self.current] = self.failures.get(self.current, 0) + 1
        nxt = self.current // 2
        if nxt >= self.min_size and nxt < self.current:
            self.current = nxt
            return True
        return self.failures[self.current] < _MAX_FAILURES_PER_SIZE


def collect_ckan_inventory_via_search(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    *,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Inventory via paginated package_search.

    Configurabile per fonte da ``inventory``:

    - ``package_search_page_size`` (default 1000)
    - ``package_search_timeout`` (default 60s)
    - ``package_search_min_page_size`` (default: nessun dimezzamento)
    - ``fq`` (filtro CKAN opzionale)

    L'adattamento della pagina (dimezzamento + recupero) è **opt-in**: scatta
    solo se ``package_search_min_page_size`` è minore del page size. I retry
    sui transitori restano delegati a ``HttpClient``; qui si riduce la pagina
    solo quando l'errore è transitorio (timeout/connessione/5xx).

    Nota: ``count`` in ``package_search`` non è affidabile su tutti i portali
    (OpenBDAP restituisce ``rows``). La paginazione termina quando arriva una
    pagina vuota o più corta del page size effettivo, mai sul ``count``.

    Args:
        client: Opzionale, ``HttpClient`` riusabile per connection pooling.
            Se non fornito, ne crea uno nuovo.
    """
    from lab_connectors.http import HttpClient

    inv = inventory_cfg(source_cfg)
    page_size = int(inv.get("package_search_page_size", DEFAULT_SEARCH_PAGE_SIZE))
    timeout = int(inv.get("package_search_timeout", DEFAULT_SEARCH_TIMEOUT))
    min_page_size = inv.get("package_search_min_page_size", DEFAULT_SEARCH_MIN_PAGE_SIZE)

    if client is None or getattr(client, "timeout", timeout) != timeout:
        # Un client condiviso con timeout diverso verrebbe sostituito a ogni
        # pagina da ckan_get_json, perdendo il connection pooling: lo si crea
        # una volta qui con il timeout giusto, riusando lo user_agent del client
        # se presente.
        user_agent = (
            getattr(client, "user_agent", None) or source_cfg.get("user_agent") or USER_AGENT
        )
        client = HttpClient(timeout=timeout, user_agent=user_agent)

    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_search")
    sizer = _PageSizer(page_size, min_page_size)
    start = 0
    ordinal = 1
    rows: list[dict[str, Any]] = []

    while True:
        used = sizer.current
        try:
            payload = ckan_get_json(
                endpoint,
                client=client,
                params=_ckan_search_params(source_cfg, page_size=used, start=start),
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — classificato subito sotto
            if _is_transient_error(exc) and sizer.on_transient_failure():
                logger.warning(
                    "CKAN %s: package_search start=%s rows=%s fallita (%s), riprovo con rows=%s",
                    source_id,
                    start,
                    used,
                    exc,
                    sizer.current,
                )
                continue
            raise

        sizer.on_success()
        if not payload.get("success"):
            raise ValueError(f"CKAN package_search failed for {source_id}")

        result = payload.get("result", {})
        items = result.get("results") or []
        if not items:
            break

        for item in items:
            rows.append(
                extract_ckan_inventory_row(
                    source_id=source_id,
                    source_cfg=source_cfg,
                    captured_at=captured_at,
                    item=item,
                    endpoint=endpoint,
                    ordinal=ordinal,
                    inventory_method="package_search",
                )
            )
            ordinal += 1

        logger.info(
            "CKAN %s: start=%s rows=%s -> %s item (totale %s)",
            source_id,
            start,
            used,
            len(items),
            len(rows),
        )

        if len(items) < used:
            break
        start += used

    if not rows:
        raise ValueError(f"CKAN package_search returned no rows for {source_id}")
    return rows


def collect_ckan_inventory_via_package_list(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    *,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    from lab_connectors.http import HttpClient

    if client is None:
        ua = source_cfg.get("user_agent") or USER_AGENT
        client = HttpClient(timeout=60, user_agent=ua)
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_list")
    payload = ckan_get_json(endpoint, client=client)
    if not payload.get("success"):
        raise ValueError(f"CKAN action failed for {source_id}")

    result = payload.get("result")
    if not isinstance(result, list):
        raise ValueError(f"Unexpected CKAN payload for {source_id}: result is not a list")

    rows: list[dict[str, Any]] = []
    for idx, item_name in enumerate(result, start=1):
        rows.append(
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": source_cfg.get("catalog_baseline", {}).get(
                    "method", "package_list"
                ),
                "item_kind": "dataset",
                "item_id": str(item_name),
                "item_name": str(item_name),
                # per fonti non-standard (es. INPS) package_list restituisce ID numerici,
                # non slug testuali — lo slug reale è disponibile solo dopo package_show_sample
                "item_slug": str(item_name),
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": endpoint,
                "api_base_url": _ckan_api_base(source_cfg.get("base_url") or endpoint),
                "ordinal": idx,
            }
        )
    return rows


def _sample_indexes(total: int, sample_size: int) -> list[int]:
    if total <= 0 or sample_size <= 0:
        return []
    if total <= sample_size:
        return list(range(total))

    indexes: set[int] = {0, total - 1}
    step = max(total // sample_size, 1)
    for idx in range(0, total, step):
        indexes.add(idx)
        if len(indexes) >= sample_size:
            break
    return sorted(indexes)


def _fetch_package_show(
    package_id: str,
    endpoint: str,
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    ordinal: int,
    timeout: int = 10,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch and process a single package_show. Returns (row_dict, error_str).

    Timeout ereditato da ``source_cfg[inventory][package_show_timeout]``
    o default 10s.
    """
    try:
        payload = ckan_get_json(endpoint, params={"id": package_id}, timeout=timeout)
        if not payload.get("success"):
            return None, f"{package_id}: success=false"
        item = payload.get("result")
        if not isinstance(item, dict):
            return None, f"{package_id}: result non-dict"
        enriched = extract_ckan_inventory_row(
            source_id=source_id,
            source_cfg=source_cfg,
            captured_at=captured_at,
            item=item,
            endpoint=endpoint,
            ordinal=ordinal,
            inventory_method="package_show_sample",
        )
        enriched["item_id"] = package_id
        return enriched, None
    except Exception as exc:
        return None, f"{package_id}: {exc}"


def collect_ckan_inventory_via_package_show_sample(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    package_list_rows: list[dict[str, Any]],
    sample_size: int = 25,
    max_workers: int = 16,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_show")
    sampled_idx = _sample_indexes(len(package_list_rows), sample_size)
    if not sampled_idx:
        return [], None

    enriched_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    # Timeout ereditato dal registry (inventory.package_show_timeout)
    inv = inventory_cfg(source_cfg)
    pkg_timeout = int(inv.get("package_show_timeout", 10))
    # Workers ereditato dal registry; default 16 se non specificato
    actual_workers = int(inv.get("package_show_max_workers", max_workers))

    # Parallel fetch — saturare la rete, non la CPU
    with ThreadPoolExecutor(max_workers=actual_workers) as pool:
        futures = {
            pool.submit(
                _fetch_package_show,
                str(package_list_rows[idx]["item_id"]),
                endpoint,
                source_id,
                source_cfg,
                captured_at,
                package_list_rows[idx]["ordinal"],
                pkg_timeout,
            ): idx
            for idx in sampled_idx
        }
        for future in as_completed(futures):
            row, err = future.result()
            if row is not None:
                enriched_rows.append(row)
            if err:
                errors.append(err)

    warning: dict[str, Any] | None = None
    if errors:
        warning = {
            "type": "package_show_sample_partial",
            "message": "Arricchimento sample via package_show completato con errori parziali.",
            "sample_size": len(sampled_idx),
            "rows_enriched": len(enriched_rows),
            "errors_preview": errors[:10],
        }
    return enriched_rows, warning


def collect(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    *,
    client: Any | None = None,
    search_fn=collect_ckan_inventory_via_search,
    package_list_fn=collect_ckan_inventory_via_package_list,
    package_show_sample_fn=collect_ckan_inventory_via_package_show_sample,
) -> CollectorResult:
    from lab_connectors.http import HttpClient

    if client is None:
        ua = source_cfg.get("user_agent") or USER_AGENT
        client = HttpClient(timeout=60, user_agent=ua)
    inv = inventory_cfg(source_cfg)
    rows, warning = _ckan_standard_path(
        source_id=source_id,
        source_cfg=source_cfg,
        captured_at=captured_at,
        inv=inv,
        client=client,
        search_fn=search_fn,
        package_list_fn=package_list_fn,
        package_show_sample_fn=package_show_sample_fn,
    )
    return CollectorResult(rows=rows, warning=warning)


def _ckan_standard_path(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    inv: dict[str, Any],
    *,
    client: Any | None = None,
    search_fn,
    package_list_fn,
    package_show_sample_fn,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Ramo standard: package_search -> fallback package_list (+ package_show_sample).

    1. Prova package_search (se non skip_package_search)
    2. Fallback: package_list (ID nudi)
    3. Se package_show_sample configurato: arricchisce con package_show
    4. Altrimenti: usa package_list così com'è
    """
    search_exc: Exception | None = None

    if not inv.get("skip_package_search"):
        try:
            rows = search_fn(source_id, source_cfg, captured_at, client=client)
            return rows, None
        except Exception as exc:
            search_exc = exc
    else:
        search_exc = ValueError(
            f"CKAN package_search disabled for {source_id} ({inv.get('skip_package_search_reason', 'disabled by registry config')})."
        )

    package_list_rows = package_list_fn(source_id, source_cfg, captured_at, client=client)

    if inv.get("package_show_sample"):
        enriched_rows, sample_warning = package_show_sample_fn(
            source_id=source_id,
            source_cfg=source_cfg,
            captured_at=captured_at,
            package_list_rows=package_list_rows,
            sample_size=inv.get("sample_size", 25),
        )
        enriched_by_id = {row["item_id"]: row for row in enriched_rows}
        merged_rows: list[dict[str, Any]] = []
        missing_metadata = 0
        for row in package_list_rows:
            enriched = enriched_by_id.get(row["item_id"])
            if enriched is None:
                missing_metadata += 1
                merged_rows.append(row)
            else:
                merged_rows.append({**row, **enriched, "ordinal": row["ordinal"]})
        warn: dict[str, Any] = {
            "type": "package_list_with_package_show_sample",
            "message": f"Enrichment via package_show_sample per {source_id}.",
            "rows_enriched": len(enriched_by_id),
            "rows_missing_metadata": missing_metadata,
            "package_search_error": str(search_exc) if search_exc is not None else None,
        }
        if sample_warning:
            warn["package_show_sample_warning"] = sample_warning
        return merged_rows, warn

    return package_list_rows, {
        "type": "fallback_package_list",
        "message": "Fallback a package_list dopo fallimento di package_search.",
        "package_search_error": str(search_exc)
        if search_exc is not None
        else "package_search skipped",
    }


def validate_items(
    items: list[dict[str, Any]],
    client: Any | None = None,
) -> dict[str, Any]:
    """Valida un gruppo di item CKAN.

    Usa il validatore tabulare standard: pick_best_url → HEAD → sniff CSV.
    ``client`` opzionale: HttpClient condiviso con circuit breaker, passato
    al validatore tabulare per mantenere lo stato breaker tra gruppi.
    """
    from ._validate_base import validate_tabular_group

    return validate_tabular_group(items, client=client)
