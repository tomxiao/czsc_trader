from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pytest

from factor_signal_catalog import CatalogRegistry, CatalogValidationError, FactorDefinition


REPO = Path(__file__).resolve().parents[4]


def test_fsc01_repository_catalog_is_complete_queryable_and_strict() -> None:
    catalog = CatalogRegistry(REPO / "catalog")
    assert len(catalog.families) >= 8
    assert len(catalog.factors) >= 10
    assert len(catalog.signals) >= 246
    assert len(catalog.digest) == 64
    assert catalog.show("F-PROJECT-ER60")["information_family"] == "TREND_REGIME"
    assert "T-1" in catalog.show("F-PROJECT-ER60")["causality"]
    assert catalog.show("F-PROJECT-BREADTH-BALANCE")["implementation"].endswith(
        "build_weighted_market_breadth_features"
    )
    assert catalog.show("F-TSFRESH-VOLUME-CONTRACTION-FLOOR-20")["status"] == "DISCOVERED"
    assert catalog.show("F-TSFRESH-ABS-RETURN-MAX-60")["information_family"] == "VOLATILITY_RISK"
    assert catalog.show("F-PROJECT-ETF-NAV-PREMIUM")["inputs"] == [
        "etf_share_size.nav",
        "etf_share_size.close",
    ]
    assert any(
        row["id"] == "SIG-CZSC-cxt_bi_base_V230228"
        for row in catalog.list_definitions(kind="signal", family="MARKET_STRUCTURE")
    )

    with pytest.raises(CatalogValidationError, match="missing fields"):
        FactorDefinition.from_dict({"factor_id": "F-BROKEN"})
    with pytest.raises(CatalogValidationError, match="unknown information family"):
        catalog.list_definitions(family="MISSING")


def test_fsc02_repository_catalog_loads_only_canonical_definition_documents() -> None:
    catalog = CatalogRegistry(REPO / "catalog")
    factor_items = json.loads((REPO / "catalog/factors/definitions.json").read_text(encoding="utf-8"))["items"]
    signal_items = json.loads((REPO / "catalog/signals/definitions.json").read_text(encoding="utf-8"))["items"]

    assert len(catalog.factors) == len(factor_items)
    assert len(catalog.signals) == len(signal_items)


def test_project_factors_resolve_to_platform_functions() -> None:
    catalog = CatalogRegistry(REPO / "catalog")
    migrated = [item for item in catalog.factors
                if item.implementation.startswith("czsc_trader.factor_features.")]
    assert len(migrated) == 11
    project_by_id = {}
    for name in ("project.json", "s007.json"):
        project = json.loads((REPO / "catalog/factors" / name).read_text(encoding="utf-8"))
        project_by_id.update({item["factor_id"]: item for item in project["items"]})
    for item in migrated:
        module, function = item.implementation.rsplit(".", 1)
        assert callable(getattr(import_module(module), function))
        assert item.version == 2
        assert item.provider == "project"
        assert item.to_dict() == project_by_id[item.factor_id]


@pytest.mark.parametrize("kind", ["factor", "signal"])
@pytest.mark.parametrize("implementation", [
    "experiments/S005/run.py", "research/S007/features.py",
    r"D:\CodeBase\czsc_trader\experiments\S005\run.py",
    "research.S007.features.calculate", "Experiments/S005/run.py",
])
def test_catalog_rejects_research_owned_implementations(tmp_path, kind, implementation):
    catalog = CatalogRegistry(REPO / "catalog")
    (tmp_path / "information_families.json").write_text(json.dumps({
        "schema_version": 1, "items": [item.to_dict() for item in catalog.families],
    }), encoding="utf-8")
    for name, items in (("factors", catalog.factors), ("signals", catalog.signals)):
        rows = [item.to_dict() for item in items]
        if name == kind + "s":
            rows[0]["implementation"] = implementation
        directory = tmp_path / name
        directory.mkdir()
        (directory / "definitions.json").write_text(json.dumps({
            "schema_version": 1, "items": rows,
        }), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="must not depend on research"):
        CatalogRegistry(tmp_path)
