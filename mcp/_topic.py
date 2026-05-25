"""Topic inference: categorise text into 20 thematic topics."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


# Keyword maps per topic. Word-boundary matches = 3pt, substring > 4 chars = 1pt.
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "lavoro": ["lavoro", "occupazione", "disoccupazione", "forze_lavoro", "OECD", "LAU", "ISTAT", "disaoccupazione", "impiego"],
    "economia": ["PIL", "GDP", "produzione", "valore_aggiunto", "conti_economici", "reddito", "economia", "crisi", "inflazione", "prezzi"],
    "sanita": ["sanita", "salute", "ospedal", "medico", "SSN", " ASL", "patologie", "mortalita", "natalita", "speranza_vita"],
    "istruzione": ["istruzione", "scuola", "universita", "studenti", "docenti", "iscritti", "laurea", "formazione", "educazione"],
    "trasporti": ["trasporti", "mobilita", "traffico", "ferrovier", "aeroporto", "porto", " merci", "passeggeri", "veicoli"],
    "ambiente": ["ambiente", "emissioni", "aria", "acqua", "rifiuti", "verde", "inquinamento", "clima"],
    "agricoltura": ["agricoltura", "coltivaz", "allevamento", "pesca", "agro", "SEMI", "superficie", "produzione_agricola"],
    "turismo": ["turismo", "flussi", "presenze", "arrivi", "strutture_ricettive", "viaggiatori", "pernottamenti"],
    "giustizia": ["giustizia", "reati", "crimini", "carceri", "procedimenti", "tribunali", "denunce"],
    "demografia": ["demografia", "popolazione", "natalita", "mortalita", "migrazioni", "invecchiamento", "indice_vecchiaia"],
    "energia": ["energia", "elettricita", "gas", "petrolio", "rinnovabili", "consumi_energetici"],
    "commercio": ["commercio", "export", "import", "interscambio", "merci", " esport", "import"],
    "welfare": ["assistenza", "sussidi", "poverta", "esclusione", "inclusione", "bonus", "assegno", "sostegno", "nucleo_familiare", "ISEE", "handicap", "invalidita", "non_autosufficienza"],
    "previdenza": ["pensione", "pensioni", "previdenza", "contributi", "pensionistico", "anzianita", "vecchiaia", "reversibilita", "quota"],
    "casa": ["casa", "edilizia", "alloggi", "residenziale", "affitto", "proprieta", "catasto", "immobiliare", "mutuo", "sfratti"],
    "cultura": ["cultura", "musei", "biblioteche", "patrimonio", "artistico", "archeologico", "monumenti", "spettacolo", "mostre"],
    "bilancio": ["bilancio", "fiscalita", "tasse", "imposte", "tributi", "gettito", "spesa_pubblica", "debito", "entrate", "erariale", "IRPEF", "IVA", "IRES"],
    "innovazione": ["innovazione", "digitale", "digitalizzaz", "tecnologia", "ICT", "banda_larga", "PA_digitale", "startup", "ricerca_sviluppo", "smart_city", "open_data", "interoperabilita"],
    "sicurezza": ["sicurezza", "protezione_civile", "emergenza", "rischio", "prevenzione", "ordine_pubblico", "forze_ordine", "polizia", "vigili_fuoco", "protezione", "soccorso"],
}


def _score_text_by_topics(text: str) -> dict[str, int]:
    """Score text against thematic topic keywords.

    Returns dict of topic -> score. Word-boundary matches = 3pt, substring matches = 1pt.
    Accented characters are normalised via NFKD.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    low = text.lower()
    scores: dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        score = 0
        for kw in keywords:
            kw_low = kw.lower()
            pattern = re.escape(kw_low)
            if re.search(rf"\b{pattern}\b", low):
                score += 3
            elif len(kw_low) > 4 and kw_low in low:
                score += 1
        if score > 0:
            scores[topic] = score
    return scores


def infer_topic(text: str) -> dict[str, Any]:
    """Infer thematic topics from any text string.

    Matches against a fixed taxonomy of 20 topics.
    Returns topics sorted by relevance score (desc), with scores.
    Also returns top_match if a dominant topic exists (score >= 3).
    """
    if not text or not str(text).strip():
        return {"error": "empty_text", "message": "Provide non-empty text to analyze."}

    scores = _score_text_by_topics(str(text))
    if not scores:
        return {
            "text_preview": str(text)[:80],
            "topics": {},
            "top_match": None,
            "matched_count": 0,
        }

    sorted_topics = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_match = sorted_topics[0][0] if sorted_topics[0][1] >= 3 else None

    return {
        "text_preview": str(text)[:80],
        "topics": dict(sorted_topics),
        "top_match": top_match,
        "matched_count": len(sorted_topics),
    }
