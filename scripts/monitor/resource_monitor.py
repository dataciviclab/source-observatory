from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
import yaml


# --- Script constants
# All paths are relative to the workspace root
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = WORKSPACE_ROOT / "data" / "monitor"

# Default paths
DEFAULT_SOURCES_PATH = SCRIPT_DIR / "resource_monitor.sources.yml"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
REPORTS_DIR = DATA_DIR / "reports"
LATEST_REPORT_PATH = REPORTS_DIR / "latest.md"
USER_AGENT = "dataciviclab-resource-diff/0.1"

DATA_EXTENSIONS = {
    ".csv",
    ".xlsx",
    ".xls",
    ".json",
    ".xml",
    ".zip",
    ".parquet",
    ".ods",
    ".tsv",
}
DATA_URL_PATTERNS = ["/download/", "/export/"]
CHANGE_PREVIEW_LIMIT = 12
DETAIL_PREVIEW_LIMIT = 8


@dataclass
class FetchResult:
    source: dict[str, Any]
    resources: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._href = dict(attrs).get("href")
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        self.links.append(
            {
                "href": self._href,
                "text": re.sub(r"\s+", " ", "".join(self._text_parts)).strip(),
            }
        )
        self._href = None
        self._text_parts = []


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def utc_now() -> datetime:
    return datetime.now(UTC)


def resource_signature(resource: dict[str, Any]) -> str:
    raw = "|".join(
        [
            resource.get("id", ""),
            resource.get("url", "") or "",
            resource.get("format", "") or "",
            resource.get("name", "") or "",
            resource.get("version", "") or "",
            resource.get("last_modified", "") or "",
        ]
    )
    return sha1_text(raw)


def fetch_ckan(source: dict[str, Any], timeout: int) -> FetchResult:
    response = requests.get(
        source["api_url"],
        params={"id": source["package_id"]},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = json.loads(response.content.decode("utf-8"))
    if not payload.get("success", True):
        error_msg = (payload.get("error") or {}).get("message") or "unknown error"
        raise ValueError(f"CKAN API returned success=False: {error_msg}")
    package = payload["result"]

    resources = []
    for r in package.get("resources", []):
        resource = {
            "id": r.get("id", ""),
            "name": normalize_whitespace(r.get("name") or r.get("description") or ""),
            "format": (r.get("format") or "").upper().strip(),
            "url": r.get("url") or "",
            "last_modified": r.get("last_modified") or r.get("metadata_modified"),
            "created": r.get("created"),
            "mimetype": r.get("mimetype"),
        }
        resource["signature"] = resource_signature(resource)
        resources.append(resource)

    return FetchResult(source=source, resources=resources)


def is_data_link(url: str) -> bool:
    url_lower = url.lower()
    suffix = Path(urlparse(url_lower).path).suffix
    if suffix in DATA_EXTENSIONS:
        return True
    return any(pattern in url_lower for pattern in DATA_URL_PATTERNS)


def fetch_html(source: dict[str, Any], timeout: int) -> FetchResult:
    response = requests.get(
        source["url"],
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()

    parser = LinkExtractor()
    parser.feed(response.content.decode("utf-8", errors="replace"))

    base_url = source["url"]
    include_patterns = [p.lower() for p in source.get("include_url_patterns", [])]
    exclude_patterns = [p.lower() for p in source.get("exclude_url_patterns", [])]

    resources = []
    seen: set[str] = set()

    for link in parser.links:
        href = link["href"]
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if absolute in seen:
            continue
        url_lower = absolute.lower()
        if include_patterns and not any(p in url_lower for p in include_patterns):
            continue
        if any(p in url_lower for p in exclude_patterns):
            continue
        if not is_data_link(absolute):
            continue

        filename = unquote(Path(parsed.path).name) or absolute
        label = link["text"].strip() or filename
        resource = {
            "id": sha1_text(absolute),
            "name": label[:120],
            "format": Path(parsed.path).suffix.lstrip(".").upper() or "",
            "url": absolute,
            "last_modified": None,
            "created": None,
            "mimetype": None,
        }
        resource["signature"] = resource_signature(resource)
        resources.append(resource)
        seen.add(absolute)

    limit = source.get("limit")
    if limit:
        resources = resources[:limit]

    return FetchResult(source=source, resources=resources)


def fetch_single_url(source: dict[str, Any], timeout: int) -> FetchResult:
    url = source.get("url")
    if not url:
        raise ValueError("single_url source requires url")

    with requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        stream=True,
    ) as response:
        response.raise_for_status()

        parsed = urlparse(url)
        filename = unquote(Path(parsed.path).name) or source.get("name") or url
        etag = normalize_whitespace(response.headers.get("ETag"))
        last_modified = normalize_whitespace(response.headers.get("Last-Modified"))
        content_type = normalize_whitespace(response.headers.get("Content-Type"))
        content_length = normalize_whitespace(response.headers.get("Content-Length"))

        resource = {
            "id": source.get("resource_id") or sha1_text(url),
            "name": source.get("resource_name") or filename[:120],
            "format": source.get("format")
            or Path(parsed.path).suffix.lstrip(".").upper()
            or "",
            "url": url,
            "last_modified": last_modified or None,
            "created": None,
            "mimetype": content_type or None,
            "etag": etag or None,
            "content_length": content_length or None,
        }
        resource["signature"] = sha1_text(
            "|".join(
                [
                    resource["id"],
                    resource["url"],
                    resource["format"],
                    resource["name"],
                    resource.get("last_modified") or "",
                    resource.get("etag") or "",
                    resource.get("content_length") or "",
                    resource.get("mimetype") or "",
                ]
            )
        )
        return FetchResult(source=source, resources=[resource])


SDMX_NAMESPACES = {
    "mes": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "str": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "com": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}


def first_text(nodes: list[ET.Element]) -> str:
    for node in nodes:
        text = normalize_whitespace(node.text)
        if text:
            return text
    return ""


def extract_sdmx_last_modified(dataflow: ET.Element, root: ET.Element) -> str | None:
    date_patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b",
    ]

    for annotation in dataflow.findall(".//com:Annotation", SDMX_NAMESPACES):
        title = normalize_whitespace(
            annotation.findtext(
                "com:AnnotationTitle", default="", namespaces=SDMX_NAMESPACES
            )
        ).lower()
        text = normalize_whitespace(
            annotation.findtext(
                "com:AnnotationText", default="", namespaces=SDMX_NAMESPACES
            )
        )
        haystack = f"{title} {text}".lower()
        if any(
            token in haystack
            for token in ("update", "updated", "aggiorn", "modified", "rilasc")
        ):
            for pattern in date_patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(0)

    prepared = normalize_whitespace(
        root.findtext("mes:Header/mes:Prepared", default="", namespaces=SDMX_NAMESPACES)
    )
    return prepared or None


def parse_sdmx_resources(xml_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    flow_filter = source.get("flow_id")
    resources: list[dict[str, Any]] = []

    for dataflow in root.findall(".//str:Dataflow", SDMX_NAMESPACES):
        flow_id = dataflow.attrib.get("id", "")
        if flow_filter and flow_id != flow_filter:
            continue

        name_nodes = dataflow.findall("com:Name", SDMX_NAMESPACES)
        flow_name = first_text(name_nodes) or flow_id or "SDMX dataflow"
        version = dataflow.attrib.get("version", "")
        agency_id = dataflow.attrib.get("agencyID", "") or source.get("agency_id", "")
        resource = {
            "id": flow_id or sha1_text(flow_name),
            "name": flow_name[:120],
            "format": "SDMX",
            "url": source.get("api_url") or source.get("url") or "",
            "last_modified": extract_sdmx_last_modified(dataflow, root),
            "created": None,
            "mimetype": "application/xml",
            "version": version,
            "agency_id": agency_id,
        }
        resource["signature"] = resource_signature(resource)
        resources.append(resource)

    return resources


def fetch_sdmx(source: dict[str, Any], timeout: int) -> FetchResult:
    endpoint = source.get("api_url") or source.get("url")
    if not endpoint:
        raise ValueError("SDMX source requires api_url or url")

    try:
        with requests.get(
            endpoint,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/xml, text/xml;q=0.9, */*;q=0.1",
            },
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            resources = parse_sdmx_resources(response.text, source)
    except requests.RequestException as exc:
        return FetchResult(source=source, error=f"SDMX fetch failed: {exc}")
    except ET.ParseError as exc:
        return FetchResult(source=source, error=f"SDMX XML parse error: {exc}")

    return FetchResult(source=source, resources=resources)


def fetch_source(source: dict[str, Any], timeout: int) -> FetchResult:
    try:
        adapter_type = source["adapter_type"]
        if adapter_type == "ckan":
            return fetch_ckan(source, timeout=timeout)
        if adapter_type == "html":
            return fetch_html(source, timeout=timeout)
        if adapter_type == "single_url":
            return fetch_single_url(source, timeout=timeout)
        if adapter_type == "sdmx":
            return fetch_sdmx(source, timeout=timeout)
        return FetchResult(
            source=source, error=f"Unsupported adapter_type: {adapter_type}"
        )
    except Exception as exc:
        return FetchResult(source=source, error=str(exc))


def latest_snapshot_path() -> Path | None:
    snapshots = sorted(SNAPSHOTS_DIR.glob("*.json"))
    return snapshots[-1] if snapshots else None


def load_snapshot(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def previous_index(
    snapshot: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    index: dict[str, dict[str, dict[str, Any]]] = {}
    if not snapshot:
        return index
    for source in snapshot.get("sources", []):
        index[source["id"]] = {
            r["id"]: r
            for r in source.get("resources", [])
            if r.get("status") != "removed"
        }
    return index


def diff_fields(current: dict[str, Any], previous: dict[str, Any]) -> list[str]:
    changes = []
    for f in ("url", "format", "name", "last_modified"):
        old = (previous.get(f) or "").strip()
        new = (current.get(f) or "").strip()
        if old != new:
            changes.append(f"{f}: {old!r} -> {new!r}")
    return changes


def annotate_resources(
    result: FetchResult,
    old_resources: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    annotated: list[dict[str, Any]] = []
    counts = {"new": 0, "changed": 0, "unchanged": 0, "removed": 0}

    for r in result.resources:
        prev = old_resources.get(r["id"])
        if prev is None:
            status, changes = "new", []
            counts["new"] += 1
        elif prev.get("signature") != r.get("signature"):
            status = "changed"
            changes = diff_fields(r, prev)
            counts["changed"] += 1
        else:
            status, changes = "unchanged", []
            counts["unchanged"] += 1
        annotated_r = dict(r)
        annotated_r["status"] = status
        annotated_r["changes"] = changes
        annotated.append(annotated_r)

    current_ids = {r["id"] for r in result.resources}
    counts["removed"] = len(set(old_resources) - current_ids)
    removed_items = [
        dict(r, status="removed", changes=[])
        for rid, r in old_resources.items()
        if rid not in current_ids
    ]
    return annotated + removed_items, counts


def read_sources(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = payload.get("sources", payload)
    if not isinstance(sources, list):
        raise ValueError(f"Invalid sources format in {path}")
    return sources


def operational_warning(source: dict[str, Any]) -> list[str]:
    if source.get("changed_count", 0) <= 0:
        return []

    lines = [f"- Source changed: `{source['id']}`"]
    di_candidate = source.get("di_candidate")
    if di_candidate and di_candidate != "~":
        lines.append(f"  - Candidate collegato: `{di_candidate}`")
        lines.append(
            "  - Verifica se i cambiamenti richiedono un aggiornamento della pipeline."
        )
    else:
        lines.append("  - Nessun candidate DI collegato nel config")

    return lines


def append_resource_preview(
    lines: list[str],
    resources: list[dict[str, Any]],
    limit: int,
    *,
    include_status: bool = False,
) -> None:
    preview = resources[:limit]
    for r in preview:
        fmt = f" [{r['format']}]" if r["format"] else ""
        modified = r.get("last_modified") or "n/a"
        prefix = f"- [{r['status']}] " if include_status else "- "
        lines.append(f"{prefix}{r['name']}{fmt} | modified: {modified} | {r['url']}")
    if len(resources) > limit:
        lines.append(f"- ... and {len(resources) - limit} more")


def build_snapshot(
    sources: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
    timeout: int,
) -> dict[str, Any]:
    run_at = utc_now()
    prev_index = previous_index(previous_snapshot)
    snapshot_sources = []

    for source in sources:
        result = fetch_source(source, timeout=timeout)
        old_resources = prev_index.get(source["id"], {})
        if result.error:
            # On fetch failure, carry forward previous resources unchanged.
            # Diffing against an empty list would misreport everything as removed.
            resources = [
                dict(r, status="unchanged", changes=[]) for r in old_resources.values()
            ]
            counts = {"new": 0, "changed": 0, "unchanged": len(resources), "removed": 0}
        else:
            resources, counts = annotate_resources(result, old_resources)
        snapshot_sources.append(
            {
                "id": source["id"],
                "name": source["name"],
                "adapter_type": source["adapter_type"],
                "status": source.get("status"),
                "di_candidate": source.get("di_candidate"),
                "tags": source.get("tags", []),
                "notes": source.get("notes"),
                "resource_count": len(
                    [r for r in resources if r["status"] != "removed"]
                ),
                "new_count": counts["new"],
                "changed_count": counts["changed"],
                "unchanged_count": counts["unchanged"],
                "removed_count": counts["removed"],
                "error": result.error,
                "resources": resources,
            }
        )

    return {
        "generated_at": run_at.isoformat(),
        "generated_at_utc": run_at.strftime("%Y-%m-%d %H:%M:%SZ"),
        "source_count": len(snapshot_sources),
        "sources": snapshot_sources,
    }


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(snapshot["generated_at"]).strftime("%Y%m%dT%H%M%SZ")
    path = SNAPSHOTS_DIR / f"{stamp}.json"
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def render_report(
    snapshot: dict[str, Any],
    previous_path: Path | None,
    snapshot_path: Path,
) -> str:
    sources = snapshot["sources"]
    total_new = sum(s["new_count"] for s in sources)
    total_changed = sum(s["changed_count"] for s in sources)
    total_removed = sum(s["removed_count"] for s in sources)
    total_errors = sum(1 for s in sources if s["error"])

    lines = [
        "# Resource Diff",
        "",
        f"- Generated at: {snapshot['generated_at_utc']}",
        f"- Snapshot: `{snapshot_path.name}`",
        f"- Previous snapshot: `{previous_path.name}`"
        if previous_path
        else "- Previous snapshot: none",
        f"- Sources checked: {snapshot['source_count']}",
        f"- New: {total_new} | Changed: {total_changed} | Removed: {total_removed} | Errors: {total_errors}",
        "",
    ]

    # Changes section: only shown when there is something actionable
    active_changes = [
        s
        for s in sources
        if s["new_count"] > 0 or s["changed_count"] > 0 or s["removed_count"] > 0
    ]

    lines.extend(["## Changes", ""])

    if active_changes:
        for s in active_changes:
            new_r = [r for r in s["resources"] if r["status"] == "new"]
            changed_r = [r for r in s["resources"] if r["status"] == "changed"]
            removed_r = [r for r in s["resources"] if r["status"] == "removed"]

            if new_r:
                lines.append(f"**{s['name']} - New**")
                append_resource_preview(lines, new_r, CHANGE_PREVIEW_LIMIT)
                lines.append("")

            if changed_r:
                lines.append(f"**{s['name']} - Changed**")
                for r in changed_r:
                    lines.append(f"- {r['name']}")
                    for change in r["changes"]:
                        lines.append(f"  - {change}")
                lines.append("")

            if removed_r:
                lines.append(f"**{s['name']} - Removed**")
                preview = removed_r[:CHANGE_PREVIEW_LIMIT]
                for r in preview:
                    fmt = f" [{r['format']}]" if r["format"] else ""
                    lines.append(f"- {r['name']}{fmt} | {r['url']}")
                if len(removed_r) > CHANGE_PREVIEW_LIMIT:
                    lines.append(
                        f"- ... and {len(removed_r) - CHANGE_PREVIEW_LIMIT} more"
                    )
                lines.append("")
    else:
        lines.extend(["- (nessuna novita)", ""])

    warning_sources = [s for s in sources if s["changed_count"] > 0]
    lines.extend(["## Operational Warnings", ""])
    if warning_sources:
        for s in warning_sources:
            lines.append(f"**{s['name']}**")
            lines.extend(operational_warning(s))
            lines.append("")
    else:
        lines.extend(["- (nessun warning operativo)", ""])

    # Summary table
    lines.extend(
        [
            "## Source Summary",
            "",
            "| Source | Adapter | Resources | New | Changed | Removed | Status |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for s in sources:
        status = "error" if s["error"] else "ok"
        lines.append(
            f"| {s['name']} | {s['adapter_type']} | {s['resource_count']} | "
            f"{s['new_count']} | {s['changed_count']} | {s['removed_count']} | {status} |"
        )

    # Details
    lines.extend(["", "## Details", ""])

    for s in sources:
        lines.append(f"### {s['name']}")
        lines.append("")
        if s.get("notes"):
            lines.append(f"- Note: {s['notes']}")
        lines.append(
            f"- Counts: {s['resource_count']} resources, {s['new_count']} new, "
            f"{s['changed_count']} changed, {s['removed_count']} removed"
        )
        if s["error"]:
            lines.append(f"- Error: `{s['error']}`")
            lines.append("")
            continue

        active = [r for r in s["resources"] if r["status"] != "removed"]
        if not active:
            lines.append("- No resources collected.")
            lines.append("")
            continue

        append_resource_preview(
            lines, active, DETAIL_PREVIEW_LIMIT, include_status=True
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_report(report: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_REPORT_PATH.write_text(report, encoding="utf-8")


DIFF_SUMMARY_PATH = REPORTS_DIR / "diff_summary.json"


def write_diff_summary(snapshot: dict[str, Any]) -> None:
    """Scrive un JSON minimale con solo le informazioni utili per consumer esterni.

    Il formato e' progettato per essere consumato da script o dalla toolkit
    senza dover parsare lo snapshot completo.
    """
    per_source: dict[str, dict[str, Any]] = {}
    sources_with_changes: list[str] = []
    sources_with_errors: list[str] = []

    for s in snapshot["sources"]:
        entry: dict[str, Any] = {
            "new": s["new_count"],
            "changed": s["changed_count"],
            "removed": s["removed_count"],
            "unchanged": s["unchanged_count"],
            "error": s.get("error"),
        }

        changed_resources = [
            {
                "id": r["id"],
                "name": r["name"],
                "format": r.get("format"),
                "url": r.get("url"),
                "fields_changed": r.get("changes", []),
            }
            for r in s.get("resources", [])
            if r.get("status") == "changed"
        ]
        new_resources = [
            {
                "id": r["id"],
                "name": r["name"],
                "format": r.get("format"),
                "url": r.get("url"),
            }
            for r in s.get("resources", [])
            if r.get("status") == "new"
        ]
        removed_resources = [
            {
                "id": r["id"],
                "name": r["name"],
                "format": r.get("format"),
                "url": r.get("url"),
            }
            for r in s.get("resources", [])
            if r.get("status") == "removed"
        ]

        if changed_resources:
            entry["changed_resources"] = changed_resources
        if new_resources:
            entry["new_resources"] = new_resources
        if removed_resources:
            entry["removed_resources"] = removed_resources

        per_source[s["id"]] = entry

        if s["changed_count"] > 0 or s["new_count"] > 0 or s["removed_count"] > 0:
            sources_with_changes.append(s["id"])
        if s["error"]:
            sources_with_errors.append(s["id"])

    summary = {
        "generated_at": snapshot["generated_at"],
        "generated_at_utc": snapshot["generated_at_utc"],
        "source_count": snapshot["source_count"],
        "sources_with_changes": sources_with_changes,
        "sources_with_errors": sources_with_errors,
        "per_source": per_source,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DIFF_SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resource-level diff for known dataset sources."
    )
    parser.add_argument(
        "--sources",
        default=str(DEFAULT_SOURCES_PATH),
        help=f"Path to sources YAML file. Default: {DEFAULT_SOURCES_PATH}",
    )
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    sources_path = Path(args.sources)

    # Fallback logic: if default sources file is missing, try the .example version
    if not sources_path.exists():
        example_path = sources_path.with_suffix(sources_path.suffix + ".example")
        if example_path.exists():
            print(f"Warning: configuration file not found at {sources_path}")
            print(f"Using example configuration: {example_path}")
            sources_path = example_path
        else:
            print(
                f"Error: configuration file not found at {sources_path} (and no .example found)"
            )
            return 1

    sources = read_sources(sources_path)
    previous_path = latest_snapshot_path()
    previous_snapshot = load_snapshot(previous_path)
    snapshot = build_snapshot(sources, previous_snapshot, timeout=args.timeout)
    snapshot_path = write_snapshot(snapshot)
    report = render_report(snapshot, previous_path, snapshot_path)
    write_report(report)
    write_diff_summary(snapshot)
    print(f"Wrote snapshot:   {snapshot_path}")
    print(f"Wrote report:     {LATEST_REPORT_PATH}")
    print(f"Wrote diff:       {DIFF_SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
