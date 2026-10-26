"""Test per scripts/catalog/drift.py — referenced-item drift check."""

from __future__ import annotations

import pytest

from scripts.catalog.drift import check_referenced_items

_INV = [
    {
        "item_id": "CRIM_GEN_REG",
        "item_name": "crim-gen-reg",
        "title": "Criminality",
        "distribution_url": "https://ex.it/data/CRIM_GEN_REG",
    },
    {
        "item_id": "sentenze-roma",
        "item_name": "tar-roma-sentenze",
        "title": "Sentenze TAR Roma",
        "distribution_url": "https://ex.it/s/roma",
    },
    {
        "item_id": "cig-2024",
        "item_name": "cig-2024",
        "title": "CIG 2024",
        "distribution_url": "https://ex.it/d/cig-2024-uuid",
    },
    {
        "item_id": "fsc-2025",
        "item_name": "fsc-2025",
        "title": "FSC 2025",
        "distribution_url": "https://docs.ex.it/2025_VAR_FSC_1_2025_csv.zip",
    },
]


def _ds(slug, refs):
    return {"slug": slug, "status": "incubating", "upstream": refs}


class TestCheckReferencedItems:
    @pytest.mark.pure_unit
    def test_empty_inventory_skips(self):
        result = check_referenced_items([_ds("a", [{"kind": "dataflow", "id": "X"}])], [])
        assert result == {"checked": 0, "matched": 0, "missing": [], "unknown": []}

    @pytest.mark.pure_unit
    def test_no_upstream(self):
        result = check_referenced_items([{"slug": "a", "status": "x"}], _INV)
        assert result == {"checked": 0, "matched": 0, "missing": [], "unknown": []}

    @pytest.mark.pure_unit
    def test_dataflow_match(self):
        ds = [_ds("g", [{"kind": "dataflow", "id": "CRIM_GEN_REG"}])]
        result = check_referenced_items(ds, _INV)
        assert result["checked"] == 1
        assert result["matched"] == 1
        assert result["missing"] == []

    @pytest.mark.pure_unit
    def test_dataflow_missing(self):
        ds = [_ds("g", [{"kind": "dataflow", "id": "NOT_EXISTS"}])]
        result = check_referenced_items(ds, _INV)
        assert result["missing"] == [{"slug": "g", "kind": "dataflow", "id": "NOT_EXISTS"}]

    @pytest.mark.pure_unit
    def test_script_type_match(self):
        ds = [_ds("ga_sentenze", [{"kind": "script_type", "id": "sentenze"}])]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1

    @pytest.mark.pure_unit
    def test_script_type_missing(self):
        ds = [_ds("x", [{"kind": "script_type", "id": "subappalti"}])]
        result = check_referenced_items(ds, _INV)
        assert len(result["missing"]) == 1

    @pytest.mark.pure_unit
    def test_ckan_dataset_match_with_placeholder(self):
        ds = [_ds("bandi", [{"kind": "ckan_dataset", "id": "cig-{year}"}])]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1  # cig-2024 matcha il prefisso cig-

    @pytest.mark.pure_unit
    def test_ckan_resource_match(self):
        ds = [_ds("a", [{"kind": "ckan_resource", "id": "cig-2024-uuid"}])]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1

    @pytest.mark.pure_unit
    def test_url_match_with_placeholder(self):
        ds = [
            _ds(
                "fsc", [{"kind": "url", "id": "https://docs.ex.it/{year}_VAR_FSC_1_{year}_csv.zip"}]
            )
        ]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1
        assert result["missing"] == []
        assert result["unknown"] == []

    @pytest.mark.pure_unit
    def test_url_missing_when_area_is_covered(self):
        """L'area (host/path) è nell'inventario ma il file referenziato no → drift."""
        ds = [
            _ds(
                "fsc", [{"kind": "url", "id": "https://docs.ex.it/{year}_VAR_FSC_9_{year}_csv.zip"}]
            )
        ]
        result = check_referenced_items(ds, _INV)
        assert len(result["missing"]) == 1
        assert result["unknown"] == []

    @pytest.mark.pure_unit
    def test_url_unknown_when_inventory_does_not_cover_area(self):
        """Nessun item dell'inventario sta in quell'area: non si può concludere."""
        ds = [_ds("x", [{"kind": "url", "id": "https://other.ex.it/data.csv"}])]
        result = check_referenced_items(ds, _INV)
        assert result["missing"] == []
        assert len(result["unknown"]) == 1


# ── URL a query-string: la query è l'identità della risorsa ──────────────────
# Regressione: il prefix match sul path nudo dichiarava "missing" (inventario che
# non copre l'area) o "matched" per costruzione (qualunque item del portale).

_MEF_HOMEPAGE_INV = [
    {
        "item_id": "reg-tipo-reddito-2025",
        "item_name": "REG_tipo_reddito_2025.csv",
        "distribution_url": "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/REG_tipo_reddito_2025.csv",
    },
    {
        "item_id": "irpef-comunale-2025",
        "item_name": "Redditi_..._CSV_2025.zip",
        "distribution_url": "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/Redditi_e_principali_variabili_IRPEF_su_base_comunale_CSV_2025.zip",
    },
]

_MEF_TREE_INV = [
    {
        "item_id": f"{code}-2025",
        "item_name": f"vista {code}",
        "distribution_url": (
            "https://www1.finanze.gov.it/finanze/analisi_stat/public/"
            f"index.php?tree=2025{code}&export=3"
        ),
    }
    for code in ("CIVATOT0202", "DIRTOT020001", "DIRTOT030001", "BASCTOT020101", "CIVATOT0301")
]

_IVA_REGIONE_REF = (
    "https://www1.finanze.gov.it/finanze/analisi_stat/public/index.php"
    "?tree={year}CIVATOT0201&export=3"
)


class TestUrlQueryString:
    @pytest.mark.pure_unit
    def test_query_as_serialization_param_still_matches(self):
        """La query può essere solo un parametro di serializzazione (ECB `?format=csvdata`)."""
        inv = [
            {"distribution_url": "https://data-api.ecb.europa.eu/service/data/BLS/IT/all"},
            {"distribution_url": "https://data-api.ecb.europa.eu/service/data/BSI/IT/all"},
        ]
        ds = [
            _ds(
                "sistema-bancario",
                [
                    {
                        "kind": "url",
                        "id": "https://data-api.ecb.europa.eu/service/data/BLS?format=csvdata",
                    }
                ],
            )
        ]
        result = check_referenced_items(ds, inv)
        assert result["matched"] == 1
        assert result["missing"] == []

    @pytest.mark.pure_unit
    def test_homepage_inventory_is_unknown_not_missing(self):
        """Inventario che copre solo la homepage: nessun falso allarme."""
        ds = [_ds("iva_regionale", [{"kind": "url", "id": _IVA_REGIONE_REF}])]
        result = check_referenced_items(ds, _MEF_HOMEPAGE_INV)
        assert result["missing"] == []
        assert result["unknown"] == [
            {"slug": "iva_regionale", "kind": "url", "id": _IVA_REGIONE_REF}
        ]

    @pytest.mark.pure_unit
    def test_tree_inventory_detects_removed_view(self):
        """Inventario dell'albero senza la vista referenziata → drift reale."""
        ds = [_ds("iva_regionale", [{"kind": "url", "id": _IVA_REGIONE_REF}])]
        result = check_referenced_items(ds, _MEF_TREE_INV)
        assert len(result["missing"]) == 1
        assert result["unknown"] == []

    @pytest.mark.pure_unit
    def test_tree_inventory_matches_own_view(self):
        """Con la vista presente, matcha il proprio export e non gli altri."""
        inv = _MEF_TREE_INV + [
            {
                "item_id": "CIVATOT0201-2025",
                "item_name": "vista CIVATOT0201",
                "distribution_url": (
                    "https://www1.finanze.gov.it/finanze/analisi_stat/public/"
                    "index.php?tree=2025CIVATOT0201&export=3"
                ),
            }
        ]
        ds = [_ds("iva_regionale", [{"kind": "url", "id": _IVA_REGIONE_REF}])]
        result = check_referenced_items(ds, inv)
        assert result["matched"] == 1
        assert result["missing"] == []

    @pytest.mark.pure_unit
    def test_non_discriminating_pattern_is_unknown(self):
        """Ref senza parte discriminante (matcha tutti gli item) → inconcludente."""
        ds = [
            _ds(
                "all",
                [
                    {
                        "kind": "url",
                        "id": "https://www1.finanze.gov.it/finanze/analisi_stat/public/index.php?tree=",
                    }
                ],
            )
        ]
        result = check_referenced_items(ds, _MEF_TREE_INV)
        assert result["matched"] == 0
        assert len(result["unknown"]) == 1

    @pytest.mark.pure_unit
    def test_mixed_match_and_missing(self):
        ds = [
            _ds(
                "g",
                [{"kind": "dataflow", "id": "CRIM_GEN_REG"}, {"kind": "dataflow", "id": "GONE"}],
            ),
            _ds("s", [{"kind": "script_type", "id": "sentenze"}]),
        ]
        result = check_referenced_items(ds, _INV)
        assert result["checked"] == 3
        assert result["matched"] == 2
        assert len(result["missing"]) == 1
        assert result["missing"][0]["id"] == "GONE"
