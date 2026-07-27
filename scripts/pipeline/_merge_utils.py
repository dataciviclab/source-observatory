"""
Merge utilities: normalize titles to group items into conceptual datasets.

Strategy:
  1. Strip ALL 4-digit years (1900-2099) from anywhere in the title
  2. Strip known Italian territorial names (regions, abbreviations, province codes)
  3. Strip variation suffixes ("e alimentazione", "e classe euro", etc.)
  4. Strip territory-prefix patterns: "{Luogo} - {Tema}" → keep Tema
  5. Collapse whitespace and slugify

Each strategy is independent and composable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# ── Known Italian territories ─────────────────────────────────────────────────

REGIONI: Final[set[str]] = {
    "abruzzo",
    "italia",
    "basilicata",
    "calabria",
    "campania",
    "emilia-romagna",
    "emilia romagna",
    "friuli-venezia-giulia",
    "friuli venezia giulia",
    "lazio",
    "liguria",
    "lombardia",
    "marche",
    "molise",
    "piemonte",
    "puglia",
    "sardegna",
    "sicilia",
    "toscana",
    "trentino-alto-adige",
    "trentino alto adige",
    "umbria",
    "valle d'aosta",
    "valle d aosta",
    "valle daosta",
    "veneto",
}

# MIM-style prefix abbreviations: ALT+{REGIONE_ABBR}
ABBR_REGIONI: Final[set[str]] = {
    "altabruz",
    "altbasil",
    "altcalab",
    "altcampa",
    "altemili",
    "altfriul",
    "altlazio",
    "altligur",
    "altlomba",
    "altmarch",
    "altmolis",
    "altpiemo",
    "altpugli",
    "altsarde",
    "altsicil",
    "alttosca",
    "alttrent",
    "altumbri",
    "altvalle",
    "altvenet",
    "alucorso",
}

# Province codes used in territorial prefixes
PROV_CODES: Final[set[str]] = {
    "ag",
    "al",
    "an",
    "ao",
    "ap",
    "aq",
    "ar",
    "at",
    "av",
    "ba",
    "bg",
    "bi",
    "bl",
    "bn",
    "bo",
    "br",
    "bs",
    "bt",
    "bz",
    "ca",
    "cb",
    "ce",
    "ch",
    "cl",
    "cn",
    "co",
    "cr",
    "cs",
    "ct",
    "cz",
    "en",
    "fc",
    "fe",
    "fg",
    "fi",
    "fm",
    "fr",
    "ge",
    "go",
    "gr",
    "im",
    "is",
    "kr",
    "lc",
    "le",
    "li",
    "lo",
    "lt",
    "lu",
    "mb",
    "mc",
    "me",
    "mi",
    "mn",
    "mo",
    "ms",
    "mt",
    "na",
    "no",
    "nu",
    "og",
    "or",
    "ot",
    "pa",
    "pc",
    "pd",
    "pe",
    "pg",
    "pi",
    "pn",
    "po",
    "pr",
    "pt",
    "pu",
    "pv",
    "pz",
    "ra",
    "rc",
    "re",
    "rg",
    "ri",
    "rm",
    "rn",
    "ro",
    "sa",
    "si",
    "so",
    "sp",
    "sr",
    "ss",
    "su",
    "sv",
    "ta",
    "te",
    "tn",
    "to",
    "tp",
    "tr",
    "ts",
    "tv",
    "ud",
    "va",
    "vb",
    "vc",
    "ve",
    "vi",
    "vr",
    "vs",
    "vt",
    "vv",
}

# Combined: all territory tokens we can strip
_TERRITORY_TOKENS: Final[set[str]] = REGIONI | ABBR_REGIONI

# ── Variation suffixes ────────────────────────────────────────────────────────

VARIATION_SUFFIXES: Final[list[str]] = [
    "e alimentazione",
    "per alimentazione",
    "e classe euro",
    "per classe euro",
    "e classe ambientale",
    "per classe ambientale",
    "mese in corso",
    "per comune",
    "per ente territoriale e alimentazione",
    "per ente territoriale e classe euro",
    "per provincia",
    "per regione",
    "per area geografica",
    "per settore",
    "per tipo",
    "per tipologia",
    "per natura giuridica",
    "per forma giuridica",
    "per destinazione",
    "per status",
    "per localizzazione",
    "per periodo",
    "per classificazione",
    "per decisione",
    "per materia",
]

# ── Temporal stopwords (remnants after year stripping) ────────────────────────

_TEMPORAL_STOPWORDS: Final[list[str]] = [
    "nel",
    "nella",
    "nelle",
    "nell",
    "dal",
    "dalla",
    "dalle",
    "dall",
    "al",
    "alla",
    "alle",
    "all",
    "anno",
    "anni",
    "dal al",
    "dal all",
    # Mesi
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
    # Numerali romani (I, II, III, IV, V)
    "i",
    "ii",
    "iii",
    "iv",
    "v",
]

# ── Utilities ─────────────────────────────────────────────────────────────────


def _html_unescape(text: str) -> str:
    """Decode common HTML entities."""
    text = text.replace("&#224;", "à").replace("&#232;", "è").replace("&#233;", "é")
    text = text.replace("&#236;", "ì").replace("&#242;", "ò").replace("&#249;", "ù")
    text = text.replace("&agrave;", "à").replace("&egrave;", "è").replace("&eacute;", "é")
    text = text.replace("&igrave;", "ì").replace("&ograve;", "ò").replace("&ugrave;", "ù")
    text = text.replace("&#224", "à").replace("&#232", "è").replace("&#233", "é")
    text = text.replace("&#236", "ì").replace("&#242", "ò").replace("&#249", "ù")
    return text


def _strip_accents(text: str) -> str:
    """Strip diacritics (à → a, è → e, etc.)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_text(text: str) -> str:
    """Lowercase, unescape HTML, strip accents, collapse whitespace."""
    t = text.lower().strip()
    t = _html_unescape(t)
    t = _strip_accents(t)
    # normalize dashes and quotes
    t = t.replace("–", "-").replace("—", "-").replace("_", " ").replace("  ", " ")
    t = t.replace("`", "'").replace("\u2018", "'").replace("\u2019", "'")
    return t


# ── Normalization strategies ─────────────────────────────────────────────────


def strip_years(text: str) -> str:
    """Strip all 4-digit years (1900-2099) from anywhere in the title.

    Handles:
      - 'nel 2022' → 'nel'
      - '2014 - Molise' → '- Molise'
      - 'anno 2023' → 'anno'
      - 'dal 2023 al 2022' → 'dal al'
      - '2017 - autovetture' → '- autovetture'
    """
    t = text
    # Year ranges: "2023 al 2022", "2020-2025", "2023/2024"
    t = re.sub(r"\d{4}\s*[-–/al]+\s*\d{4}", "", t)
    # Standalone years
    t = re.sub(r"\b(?:19|20)\d{2}\b", "", t)
    # Clean up leftover whitespace from year removal
    t = re.sub(r"\s{2,}", " ", t).strip()
    # Clean trailing/leading hyphens/dashes left by year removal
    t = re.sub(r"\s*[-–]+\s*$", "", t)
    t = re.sub(r"^\s*[-–]+\s*", "", t)
    return t.strip()


def strip_territory_suffix(text: str) -> str:
    """Strip trailing territory suffixes.

    Handles:
      - 'provincia-di-modena' → ''
      - 'per comune' → ''
      - 'della provincia di X' → ''
      - 'nella provincia di X' → ''
    """
    t = text
    # "della provincia di X" / "nella provincia di X" / "per provincia"
    t = re.sub(
        r"\s+(?:della|nella|per)\s+provincia\s+di\s+[a-z\s-]+$",
        "",
        t,
    )
    # "provincia di X"
    t = re.sub(r"\s+provincia\s+di\s+[a-z\s-]+$", "", t)
    # Strip trailing territory words like "regionale", "nazionale"
    t = re.sub(r"\s+(?:regionale|nazionale|provinciale)\s*$", "", t)
    # Strip trailing region names (INAIL: "per data protocollo Piemonte" → "per data protocollo")
    # Multi-word regions (emilia romagna, valle d'aosta) sorted by length for greedy match
    _reg_sorted = sorted(REGIONI, key=len, reverse=True)
    t = re.sub(r"\s+(" + "|".join(_reg_sorted) + r")\s*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def strip_territory_prefix(text: str) -> str:
    """Strip known territory prefixes (regions, MI/MIM-style abbreviations).

    Handles:
      - 'altabruz istruzione' → 'istruzione'
      - 'molise - siope movimenti' → 'siope movimenti'
      - 'lazio - siope movimenti' → 'siope movimenti'
    """
    t = text

    # MIM-style: ALT+{ABBR} tema
    # We need to match 'altXXX ' at start
    for abbr in ABBR_REGIONI:
        if t.startswith(abbr):
            t = t[len(abbr) :].strip()
            break

    # Region name at start, possibly followed by " - " or " "
    # e.g. "molise - siope", "lazio - siope"
    for reg in REGIONI:
        # Check if title starts with region name
        prefix = reg
        if t.startswith(prefix):
            t = t[len(prefix) :].strip().lstrip("-").strip()
            break

    return t.strip()


def strip_variation_suffix(text: str) -> str:
    """Strip variation/version suffixes.

    Handles ACI-style: 'per ente territoriale e alimentazione'
    Handles time qualifiers: 'mese in corso'
    """
    t = text
    for suffix in VARIATION_SUFFIXES:
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
            break
    return t.strip()


def strip_territory_prefix_pattern(text: str) -> str:
    """Strip '{Luogo} - {Tema}' prefix patterns.

    Handles Unioncamere-style:
      'Alto Piemonte (BI NO VB VC) - Export Imprese dal 2023 al 2022'
      'Aosta - Imprese artigiane valdostane per natura giuridica anno 2024'

    After years are stripped, becomes:
      'Alto Piemonte (bi no vb vc) - export imprese'
      'aosta - imprese artigiane valdostane per natura giuridica anno'

    We detect: if first segment before " - " contains known territory
    (province codes in parens, region name, etc.), strip it.
    """
    if " - " not in text:
        return text

    parts = text.split(" - ", 1)
    prefix = parts[0].strip()

    # Check for province codes in parentheses: "(BI NO VB VC)"
    if re.search(r"\([a-z\s]{2,}\)", prefix):
        return parts[1].strip()

    # Check if prefix is a known territory or common city name
    # (simple heuristic: short prefix that's a known location)
    # Strip Lombardia-style prefixes like 'aosta', 'milano', 'torino'
    known_cities = {
        "aosta",
        "milano",
        "torino",
        "genova",
        "roma",
        "napoli",
        "bari",
        "palermo",
        "cagliari",
        "firenze",
        "bologna",
        "venezia",
        "verona",
        "padova",
        "trieste",
        "ancona",
        "perugia",
        "l'aquila",
        "campobasso",
        "potenza",
        "catanzaro",
        "reggio calabria",
        "modena",
        "alto piemonte",
        "arezzo-siena",
    }
    # Match città note o regioni/province
    if prefix in known_cities or prefix in _TERRITORY_TOKENS:
        return parts[1].strip()

    return text


def strip_temporal_stopwords(text: str) -> str:
    """Strip temporal stopwords left over after year removal.

    Handles:
      - 'nel - autovetture' → '- autovetture'  (ACI after year strip)
      - 'dal al' → ''  (Unioncamere after year range strip)
      - 'anno - imprese' → 'imprese'
    """
    t = text
    # Remove leading temporal words
    for sw in _TEMPORAL_STOPWORDS:
        # At start of text or after space
        if t.startswith(sw + " "):
            t = t[len(sw) :].strip()
        # In middle: "nel -"  → just strip the temporal word
        t = re.sub(r"\s+" + re.escape(sw) + r"\s+", " ", t)
        # At end
        if t.endswith(" " + sw):
            t = t[: -(len(sw) + 1)].strip()
    # Strip month names inside parentheses: "(mese anno)" → "( )" → ""
    t = re.sub(r"\(\s*(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s*\)", "", t)
    # Also handle "nel -" pattern specifically (year was stripped leaving "nel -")
    t = re.sub(r"\b(?:nel|nella|nell|dal|dall|al)\s*[-–]\s*", "", t)
    # Clean "- " artifacts
    t = re.sub(r"\s*[-–]+\s*", " ", t)
    return t.strip()


def strip_leading_year_prefix(text: str) -> str:
    """Strip leading year prefix like '2014 -', '2015 -', '2018/02 -'.

    Handles OpenBDAP style:
      '2014 - Molise - SIOPE...' → 'Molise - SIOPE...'
      '2018/02 - Pagamenti...' → 'Pagamenti...'
    """
    t = re.sub(r"^\d{4}[-/]\d{2}\s*[-–]\s*", "", text)
    t = re.sub(r"^\d{4}\s*[-–]\s*", "", t)
    return t.strip()


# ── Main normalization pipeline ──────────────────────────────────────────────


def normalize_title_for_merge(title: str) -> str:
    """Normalize a title to extract the conceptual dataset core.

    Pipeline (order matters):
      1. Normalize (lowercase, unescape, accents)
      2. Strip leading year prefix  (OpenBDAP: '2014 - Molise - ...')
      3. Strip ALL years anywhere
      4. Strip territory prefix (MIM: 'altabruz istruzione')
      5. Strip territory prefix pattern (Unioncamere: 'Luogo - Tema')
      6. Strip variation suffix (ACI: 'e alimentazione')
      7. Strip territory suffix ('provincia di modena')
      8. Strip HTML entities, collapse whitespace

    Returns empty string if nothing meaningful remains.
    """
    if not title or not isinstance(title, str):
        return ""

    t = _normalize_text(title)

    # Final collapse & cleanup
    t = strip_leading_year_prefix(t)
    t = strip_years(t)
    t = strip_territory_prefix(t)
    # Territory prefix pattern detection needs the " - " separator intact,
    # so it must run BEFORE strip_temporal_stopwords cleans up hyphens.
    t = strip_territory_prefix_pattern(t)
    t = strip_temporal_stopwords(t)
    t = strip_variation_suffix(t)
    t = strip_territory_suffix(t)

    # Collapse whitespace and strip leftover separators
    t = re.sub(r"\s+", " ", t).strip()
    t = t.rstrip(".,;:-–_ ")
    t = t.strip("-–").strip()
    return t


def to_slug(text: str, max_len: int = 80) -> str:
    """Convert free text to a filesystem-safe slug."""
    if not text:
        return "unknown"
    s = text.lower().strip()
    # Convert underscores and whitespace to hyphens first
    s = re.sub(r"[\s_]+", "-", s)
    # Remove any remaining non-alphanumeric (except hyphens)
    s = re.sub(r"[^a-z0-9-]", "", s)
    # Collapse multiple hyphens
    s = re.sub(r"-+", "-", s)
    return s.strip("-")[:max_len]


def _item_id_stem(item_id: str) -> str | None:
    """Extract the meaningful stem from an item_id, stripping trailing year.

    Handles:
      - 'REG_tipo_reddito_2025' → 'reg-tipo-reddito'
      - 'cla_anno_calcolo_irpef_2023' → 'cla-anno-calcolo-irpef'
      - 'sesso_tipo_reddito_2019' → 'sesso-tipo-reddito'
      - 'Redditi_e_..._CSV_2024' → 'redditi-e-p...csv'
      - UUID or hash → None (not meaningful)
    """
    if not item_id or not isinstance(item_id, str):
        return None
    # Strip trailing year (4 digits at end, possibly preceded by _)
    stem = re.sub(r"_?(?:19|20)\d{2}$", "", item_id.strip())
    # If stem is too short or same as original, not useful
    if len(stem) < 5 or stem == item_id.strip():
        return None
    # Also strip trailing _YYYY pattern in middle
    stem = re.sub(r"_?(?:19|20)\d{2}$", "", stem)
    # Convert to slug
    slug = to_slug(stem)
    # Skip if looks like a UUID (hex with hyphens)
    if re.match(r"^[a-f0-9-]{20,}$", slug):
        return None
    return slug if len(slug) > 3 else None


def compute_dataset_group(
    source_id: str,
    title: str | None,
    item_id: str | None,
    protocol: str | None = None,
) -> str:
    """Compute a ``dataset_group`` slug for an inventory item.

    Strategy (first match wins):

    1. **Normalized title** — if a meaningful title exists, strip years,
       territories and variations.  If the title is too generic (short slug
       shared by many items), disambiguate with ``item_id`` stem.
    2. **SDMX prefix** — for SDMX items, strip the trailing ``_\\d+``
       version suffix from the item_id.
    3. **item_id stem** — extract meaningful prefix from item_id.
    4. **item_id fallback** — use the item_id itself.
    5. **unknown**.
    """
    # Strategy 1: normalized title
    if title and isinstance(title, str) and len(title.strip()) > 5:
        norm = normalize_title_for_merge(title)
        if norm and len(norm) > 3:
            slug = to_slug(norm)
            # Disambiguate with item_id stem when the title is shared
            # across many items (e.g., MEF IRPEF: same title for all).
            # Only append stem when it adds info NOT already in slug.
            stem = _item_id_stem(item_id) if item_id else None
            if stem and stem not in slug:
                return f"{source_id}/{slug}/{stem}"[:120]
            return f"{source_id}/{slug}"[:120]

    # Strategy 2: SDMX — strip trailing version suffix
    if item_id:
        iid = str(item_id)
        if protocol == "sdmx":
            core = re.sub(r"_\d+$", "", iid)
            if len(core) > 5:
                return f"{source_id}/sdmx/{to_slug(core)}"[:120]
        # Strategy 3: item_id stem
        stem = _item_id_stem(iid)
        if stem:
            return f"{source_id}/{stem}"[:120]
        # Strategy 4: plain item_id
        if len(iid) > 3:
            return f"{source_id}/{to_slug(iid)}"[:120]

    return f"{source_id}/unknown"


def add_dataset_group_columns(df):
    """Add ``dataset_group``, ``dataset_group_size`` and year range columns.

    This is a pure-dataframe operation — no I/O, no side effects.
    """
    import pandas as pd

    df = df.copy()
    for col in ("year_min", "year_max"):
        if col not in df.columns:
            if "year_signal" in df.columns:
                df[col] = df["year_signal"]
            else:
                df[col] = None

    df["dataset_group"] = df.apply(
        lambda r: compute_dataset_group(
            source_id=str(r.get("source_id", "")),
            title=r.get("title") if pd.notna(r.get("title")) else None,
            item_id=str(r.get("item_id", "")),
            protocol=str(r.get("protocol", "")) if "protocol" in r.index else None,
        ),
        axis=1,
    )

    group_agg = (
        df.groupby("dataset_group")
        .agg(
            dataset_group_size=("item_id", "count"),
            dataset_group_year_min=("year_min", "min"),
            dataset_group_year_max=("year_max", "max"),
        )
        .reset_index()
    )

    for col in ("dataset_group_size", "dataset_group_year_min", "dataset_group_year_max"):
        if col in df.columns:
            df = df.drop(columns=[col])

    df = df.merge(group_agg, on="dataset_group", how="left")
    return df
