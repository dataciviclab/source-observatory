"""
Test merge utilities with real titles from inventory.

Each test case is a (title, expected_group_slug) pair from actual data.
"""

from __future__ import annotations

import pytest

from scripts.pipeline._merge_utils import (
    add_dataset_group_columns,
    compute_dataset_group,
    normalize_title_for_merge,
    strip_leading_year_prefix,
    strip_territory_prefix,
    strip_territory_prefix_pattern,
    strip_variation_suffix,
    strip_years,
)

pytestmark = pytest.mark.pure_unit

# ── Unit: strip_years ─────────────────────────────────────────────────────────


class TestStripYears:
    def test_trailing_year(self):
        assert strip_years("popolazione residente 2021") == "popolazione residente"

    def test_year_in_middle(self):
        assert (
            strip_years("prime iscrizioni veicoli nuovi nel 2022 autovetture")
            == "prime iscrizioni veicoli nuovi nel autovetture"
        )

    def test_leading_year(self):
        assert strip_years("2014 molise siope movimenti") == "molise siope movimenti"

    def test_year_range(self):
        result = strip_years("export imprese dal 2023 al 2022")
        assert "2023" not in result
        assert "2022" not in result

    def test_year_with_slash(self):
        result = strip_years("2023/09 pagamenti bilancio")
        assert "2023" not in result
        assert "09" in result  # month preserved

    def test_multiple_years(self):
        result = strip_years("2008-2011 modello di rilevazione")
        assert "2008" not in result
        assert "2011" not in result

    def test_no_years_preserves_text(self):
        assert strip_years("popolazione residente") == "popolazione residente"

    def test_empty_string(self):
        assert strip_years("") == ""

    def test_anno_prefix(self):
        result = strip_years("imprese femminili anno 2023")
        assert "2023" not in result


# ── Unit: strip_territory_prefix ─────────────────────────────────────────────


class TestStripTerritoryPrefix:
    def test_mim_altabruz(self):
        assert strip_territory_prefix("altabruz istruzione") == "istruzione"

    def test_mim_altbasil(self):
        assert strip_territory_prefix("altbasil istruzione") == "istruzione"

    def test_mim_altemili(self):
        assert strip_territory_prefix("altemili istruzione") == "istruzione"

    def test_region_prefix_with_dash(self):
        assert strip_territory_prefix("molise - siope movimenti") == "siope movimenti"

    def test_region_prefix_no_dash(self):
        assert strip_territory_prefix("lazio siope movimenti") == "siope movimenti"

    def test_no_territory_prefix(self):
        assert strip_territory_prefix("popolazione residente") == "popolazione residente"

    def test_alucorso_preserved(self):
        """ALCORSO appears multiple times in MIM data — should match."""
        result = strip_territory_prefix("alucorso istruzione")
        assert result == "istruzione"


# ── Unit: strip_variation_suffix ──────────────────────────────────────────────


class TestStripVariationSuffix:
    def test_e_alimentazione(self):
        assert (
            strip_variation_suffix(
                "prime iscrizioni veicoli nuovi nel autovetture per ente territoriale e alimentazione"
            )
            == "prime iscrizioni veicoli nuovi nel autovetture per ente territoriale"
        )

    def test_e_classe_euro(self):
        assert (
            strip_variation_suffix(
                "radiazioni per demolizione nel autovetture per ente territoriale e classe euro"
            )
            == "radiazioni per demolizione nel autovetture per ente territoriale"
        )

    def test_mese_in_corso(self):
        assert strip_variation_suffix("certificati mese in corso") == "certificati"

    def test_no_suffix(self):
        assert strip_variation_suffix("popolazione residente") == "popolazione residente"


# ── Unit: strip_territory_prefix_pattern ──────────────────────────────────────


class TestStripTerritoryPrefixPattern:
    def test_unioncamere_alto_piemonte(self):
        """Alto Piemonte (BI NO VB VC) - Export Imprese → Export Imprese"""
        result = strip_territory_prefix_pattern("alto piemonte (bi no vb vc) - export imprese")
        assert result == "export imprese"

    def test_unioncamere_aosta(self):
        result = strip_territory_prefix_pattern("aosta - imprese artigiane valdostane")
        assert result == "imprese artigiane valdostane"

    def test_unioncamere_arezzo_siena(self):
        result = strip_territory_prefix_pattern("arezzo-siena - imprese femminili")
        assert result == "imprese femminili"

    def test_unioncamere_modena(self):
        """modena is a known city in known_cities set."""
        result = strip_territory_prefix_pattern("modena - esportazioni settore ceramico")
        assert result == "esportazioni settore ceramico"

    def test_no_prefix(self):
        assert strip_territory_prefix_pattern("popolazione residente") == "popolazione residente"


# ── Unit: strip_leading_year_prefix ───────────────────────────────────────────


class TestStripLeadingYearPrefix:
    def test_openbdap_style(self):
        assert strip_leading_year_prefix("2014 - Molise - SIOPE") == "Molise - SIOPE"

    def test_openbdap_with_slash(self):
        assert strip_leading_year_prefix("2018/02 - Pagamenti Bilancio") == "Pagamenti Bilancio"

    def test_no_prefix(self):
        assert strip_leading_year_prefix("Popolazione residente") == "Popolazione residente"


# ── Integration test: normalize_title_for_merge with REAL titles ──────────────


class TestNormalizeTitleForMerge:
    """Test with actual titles from inventory — this is the real spec."""

    # ── ACI: year-in-middle pattern ─────────────────────────────────────────

    def test_aci_prime_iscrizioni_2017(self):
        """All ACI 'Prime iscrizioni veicoli nuovi nel {ANNO}' should merge."""
        norm = normalize_title_for_merge(
            "Prime Iscrizioni veicoli nuovi nel 2017 - autovetture per ente territoriale"
        )
        assert norm == "prime iscrizioni veicoli nuovi autovetture per ente territoriale"
        # "nel" is a temporal stopword removed after year strip
        assert "nel" not in norm

    def test_aci_prime_iscrizioni_2024(self):
        """Same dataset, different year → same normalized form."""
        norm = normalize_title_for_merge(
            "Prime iscrizioni veicoli nuovi nel 2024 - autovetture per ente territoriale"
        )
        assert "2024" not in norm

    def test_aci_prime_iscrizioni_alimentazione_2017(self):
        """With 'e alimentazione' suffix — should merge with base."""
        norm = normalize_title_for_merge(
            "Prime iscrizioni veicoli nuovi nel 2017 - autovetture per ente territoriale e alimentazione"
        )
        assert "alimentazione" not in norm

    def test_aci_radiazioni_2024(self):
        """Different series (radiazioni) → different group from prime-iscrizioni."""
        norm = normalize_title_for_merge(
            "Radiazioni per demolizione nel 2024 - autovetture per ente territoriale"
        )
        assert norm.startswith("radiazioni per demolizione")

    def test_aci_radiazioni_classe_euro_2024(self):
        """Radiazioni + classe euro — should merge with base radiazioni."""
        norm = normalize_title_for_merge(
            "Radiazioni per demolizione nel 2024 - autovetture per ente territoriale e classe euro"
        )
        assert "classe euro" not in norm

    def test_aci_dataset_territorio(self):
        """ACI also has aggregate ZIP datasets — must not collide with per-year."""
        norm = normalize_title_for_merge("Dataset Territorio")
        assert norm == "dataset territorio"

    # ── OpenBDAP: year-prefix + territory pattern ──────────────────────────

    def test_openbdap_siope_2014_molise_entrata(self):
        norm = normalize_title_for_merge(
            "2014 - Molise - SIOPE Movimenti cumulati mensili di Entrata"
        )
        assert "molise" not in norm
        assert "2014" not in norm
        assert norm == "siope movimenti cumulati mensili di entrata"

    def test_openbdap_siope_2015_lazio_entrata(self):
        """Same tipo (entrata), different region/year → same normalized form."""
        norm = normalize_title_for_merge(
            "2015 - Lazio - SIOPE Movimenti cumulati mensili di Entrata"
        )
        assert "lazio" not in norm
        assert "2015" not in norm
        assert norm == "siope movimenti cumulati mensili di entrata"

    def test_openbdap_siope_spesa_different_from_entrata(self):
        """Entrata and Spesa are genuinely different datasets (different fact tables)."""
        entrata = normalize_title_for_merge(
            "2014 - Molise - SIOPE Movimenti cumulati mensili di Entrata"
        )
        spesa = normalize_title_for_merge(
            "2015 - Lazio - SIOPE Movimenti cumulati mensili di Spesa"
        )
        assert entrata != spesa
        assert "spesa" in spesa
        assert "entrata" in entrata

    def test_openbdap_dipendenti_2015(self):
        norm = normalize_title_for_merge(
            "2015 - Dipendenti Pubblici - Anzianità - Dati analitici per Ente"
        )
        assert "2015" not in norm
        assert norm.startswith("dipendenti pubblici")

    # ── Unioncamere: territory prefix pattern ──────────────────────────────

    def test_unioncamere_alto_piemonte_export(self):
        norm = normalize_title_for_merge(
            "Alto Piemonte (BI NO VB VC) - Export Imprese dal 2023 al 2022"
        )
        assert "alto piemonte" not in norm
        assert norm == "export imprese"

    def test_unioncamere_aosta_export(self):
        """Same theme (export imprese) from different territory → same normalized form."""
        norm = normalize_title_for_merge("Aosta - Export Imprese anno 2023")
        assert "aosta" not in norm
        assert norm == "export imprese"

    def test_unioncamere_aosta_imprese_femminili(self):
        norm = normalize_title_for_merge(
            "Aosta - Imprese femminili valdostane per natura giuridica anno 2023"
        )
        assert "aosta" not in norm
        assert "2023" not in norm
        assert norm.startswith("imprese femminili")

    def test_unioncamere_modena_esportazioni(self):
        norm = normalize_title_for_merge(
            "Modena - Esportazioni settore ceramico provincia di Modena"
        )
        assert "modena" not in norm
        assert norm.startswith("esportazioni settore ceramico")

    # ── Ministero Interno: trailing year pattern ───────────────────────────

    def test_mininterno_attivita_residenti_2021(self):
        norm = normalize_title_for_merge("Attività residenti 2021")
        assert norm == "attivita residenti"

    def test_mininterno_attivita_residenti_2023(self):
        norm = normalize_title_for_merge("Attività residenti 2023")
        assert norm == "attivita residenti"

    def test_mininterno_elezioni_comunali_2016(self):
        norm = normalize_title_for_merge(
            "Elezioni comunali 2016  - elettori e votanti per comune I turno"
        )
        assert "2016" not in norm
        assert norm.startswith("elezioni comunali")

    def test_mininterno_elezioni_comunali_2024(self):
        norm = normalize_title_for_merge("Elezioni Comunali 2024")
        assert norm.startswith("elezioni comunali")

    # ── MIM opendata: regional prefix ──────────────────────────────────────

    def test_mim_altabruz_istruzione(self):
        norm = normalize_title_for_merge("ALTABRUZ istruzione")
        assert norm == "istruzione"

    def test_mim_altbasil_istruzione(self):
        norm = normalize_title_for_merge("ALTBASIL istruzione")
        assert norm == "istruzione"

    def test_mim_alucorso_istruzione(self):
        norm = normalize_title_for_merge("ALUCORSO istruzione")
        assert norm == "istruzione"

    # ── INPS: trailing year (simple pattern) ───────────────────────────────

    def test_inps_anf_2014(self):
        norm = normalize_title_for_merge(
            "ANF concessi dai comuni. Numero beneficiari per area geografica 2014"
        )
        assert "2014" not in norm
        assert norm.startswith("anf concessi dai comuni")

    def test_inps_aliquote_agricoltura(self):
        """Aliquote contributive Agricoltura I, II, III... → should stay distinct."""
        norm = normalize_title_for_merge("Aliquote contributive Agricoltura I")
        assert norm.startswith("aliquote contributive agricoltura")

    # ── OpenGA ──────────────────────────────────────────────────────────────

    def test_openga_cds_calendario(self):
        norm = normalize_title_for_merge("CDS - Calendario Udienze")
        assert norm.startswith("cds calendario udienze")

    def test_openga_tar_ricorsi(self):
        """TAR Ricorsi: court prefix + region + city. Theme is 'ricorsi pendenti'."""
        norm = normalize_title_for_merge(
            "TAR Emilia Romagna Bologna - Ricorsi pendenti per periodo"
        )
        # The core theme "ricorsi pendenti" is preserved
        assert "ricorsi pendenti" in norm

    # ── Edge cases ────────────────────────────────────────────────────────

    def test_empty_title(self):
        assert normalize_title_for_merge("") == ""

    def test_none_title(self):
        assert normalize_title_for_merge(None) == ""

    def test_html_entities(self):
        norm = normalize_title_for_merge(
            "ANF concessi dai comuni. Numero beneficiari per classe di et&#224; 2014"
        )
        assert "&#224;" not in norm
        assert "eta" in norm

    def test_very_long_title_preserves_core(self):
        title = (
            "Procedura aperta per l'affidamento in concessione della progettazione "
            "esecutiva e della realizzazione dei lavori di ammodernamento della strada "
            "statale 18 - Lotto 1 - anno 2023"
        )
        norm = normalize_title_for_merge(title)
        assert "2023" not in norm
        assert len(norm) > 10  # meaningful content remains


# ── Integration: compute_dataset_group ────────────────────────────────────────


class TestComputeDatasetGroup:
    def test_aci_prime_iscrizioni_2017(self):
        g1 = compute_dataset_group(
            "aci",
            "Prime Iscrizioni veicoli nuovi nel 2017 - autovetture per ente territoriale",
            "item_1",
        )
        g2 = compute_dataset_group(
            "aci",
            "Prime iscrizioni veicoli nuovi nel 2024 - autovetture per ente territoriale",
            "item_2",
        )
        assert g1 == g2, f"{g1} != {g2}"
        assert g1.startswith("aci/prime-iscrizioni-veicoli-nuovi")

    def test_aci_prime_iscrizioni_alimentazione_merges(self):
        """With and without 'e alimentazione' → same group."""
        g1 = compute_dataset_group(
            "aci",
            "Prime iscrizioni veicoli nuovi nel 2022 - autovetture per ente territoriale",
            "item_a",
        )
        g2 = compute_dataset_group(
            "aci",
            "Prime iscrizioni veicoli nuovi nel 2022 - autovetture per ente territoriale e alimentazione",
            "item_b",
        )
        assert g1 == g2

    def test_aci_radiazioni_different_from_prime(self):
        """Radiazioni is a different conceptual dataset from prime-iscrizioni."""
        g1 = compute_dataset_group(
            "aci",
            "Prime iscrizioni veicoli nuovi nel 2024 - autovetture per ente territoriale",
            "a",
        )
        g2 = compute_dataset_group(
            "aci", "Radiazioni per demolizione nel 2024 - autovetture per ente territoriale", "b"
        )
        assert g1 != g2

    def test_openbdap_siope_molise_and_lazio_same_group_entrata(self):
        """Same fact table (entrata), different regions → same group."""
        g1 = compute_dataset_group(
            "openbdap", "2014 - Molise - SIOPE Movimenti cumulati mensili di Entrata", "item_1"
        )
        g2 = compute_dataset_group(
            "openbdap", "2015 - Lazio - SIOPE Movimenti cumulati mensili di Entrata", "item_2"
        )
        assert g1 == g2, f"SIOPE Entrata groups differ: {g1} vs {g2}"

    def test_openbdap_siope_entrata_vs_spesa_different(self):
        """Entrata and Spesa are different fact tables → different groups."""
        g1 = compute_dataset_group(
            "openbdap", "2014 - Molise - SIOPE Movimenti cumulati mensili di Entrata", "a"
        )
        g2 = compute_dataset_group(
            "openbdap", "2015 - Lazio - SIOPE Movimenti cumulati mensili di Spesa", "b"
        )
        assert g1 != g2, "Entrata and Spesa should NOT merge"

    def test_unioncamere_alto_piemonte_and_aosta_export_same_group(self):
        """Export Imprese from different territories → same group."""
        g1 = compute_dataset_group(
            "unioncamere", "Alto Piemonte (BI NO VB VC) - Export Imprese dal 2023 al 2022", "a"
        )
        g2 = compute_dataset_group("unioncamere", "Aosta - Export Imprese anno 2023", "b")
        assert g1 == g2, f"Export groups: {g1} vs {g2}"

    def test_mim_altabruz_and_altbasil_merge(self):
        g1 = compute_dataset_group("mim_opendata", "ALTABRUZ istruzione", "a")
        g2 = compute_dataset_group("mim_opendata", "ALTBASIL istruzione", "b")
        # Both normalize to "istruzione" — but that's too generic
        # Actually this depends on how aggressive we are
        # Both should merge into same group
        assert g1 == g2, f"MIM groups: {g1} vs {g2}"

    def test_mininterno_attivita_residenti_merges(self):
        g1 = compute_dataset_group("ministero_interno", "Attività residenti 2021", "a")
        g2 = compute_dataset_group("ministero_interno", "Attività residenti 2023", "b")
        assert g1 == g2

    def test_inps_aliquote_agricoltura_merges(self):
        """Aliquote Agricoltura I and II merge (Roman numerals stripped)."""
        g1 = compute_dataset_group("inps", "Aliquote contributive Agricoltura I", "a")
        g2 = compute_dataset_group("inps", "Aliquote contributive Agricoltura II", "b")
        assert g1 == g2, "Roman numerals I/II should be stripped for merge"

    def test_sdmx_fallback(self):
        g = compute_dataset_group(
            "istat_sdmx", None, "164_279_DF_DCIS_RICPOPRES1991_15", protocol="sdmx"
        )
        assert g.startswith("istat_sdmx/sdmx/")

    def test_item_id_fallback(self):
        g = compute_dataset_group("anac", None, "da10182d-75ba-4894")
        assert g.startswith("anac/")

    def test_unknown_fallback(self):
        g = compute_dataset_group("x", None, None)
        assert g == "x/unknown"


# ── Dataframe integration ─────────────────────────────────────────────────────


class TestAddDatasetGroupColumns:
    def test_adds_columns(self):
        import pandas as pd

        df = pd.DataFrame(
            {
                "source_id": ["aci", "aci"],
                "title": [
                    "Prime iscrizioni veicoli nuovi nel 2022 - autovetture per ente territoriale",
                    "Prime iscrizioni veicoli nuovi nel 2023 - autovetture per ente territoriale",
                ],
                "item_id": ["a", "b"],
                "year_min": [2022, 2023],
                "year_max": [2022, 2023],
            }
        )
        result = add_dataset_group_columns(df)
        assert "dataset_group" in result.columns
        assert "dataset_group_size" in result.columns
        assert result["dataset_group"].iloc[0] == result["dataset_group"].iloc[1]
        assert result["dataset_group_size"].iloc[0] == 2

    def test_preserves_existing_group_columns(self):
        import pandas as pd

        df = pd.DataFrame(
            {
                "source_id": ["aci"],
                "title": ["Prime iscrizioni veicoli nuovi nel 2022 - autovetture"],
                "item_id": ["a"],
                "dataset_group": ["aci/old-group"],
                "dataset_group_size": [1],
            }
        )
        result = add_dataset_group_columns(df)
        # Should overwrite with fresh computation
        assert result["dataset_group"].iloc[0] != "aci/old-group"

    def test_handles_missing_year_columns(self):
        import pandas as pd

        df = pd.DataFrame(
            {
                "source_id": ["aci"],
                "title": ["Prime iscrizioni veicoli nuovi nel 2022 - autovetture"],
                "item_id": ["a"],
            }
        )
        result = add_dataset_group_columns(df)
        assert "dataset_group" in result.columns
        assert result["dataset_group_year_min"].iloc[0] is None or pd.isna(
            result["dataset_group_year_min"].iloc[0]
        )
