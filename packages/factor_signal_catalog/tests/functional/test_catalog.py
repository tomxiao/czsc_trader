from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pytest

from factor_signal_catalog import (
    CatalogRegistry, CatalogStatus, CatalogValidationError, FactorDefinition,
    InformationFamily, SignalDefinition,
)


REPO = Path(__file__).resolve().parents[4]


@pytest.fixture
def minimal_catalog(tmp_path):
    family = InformationFamily("PRICE", "Price", "Completed prices", CatalogStatus.READY)
    factor = FactorDefinition(
        factor_id="F-PRICE", name="Daily range", description="Completed daily range",
        information_family="PRICE", tags=("daily",), inputs=("daily.high", "daily.low"),
        provider="project", implementation="factor_signal_catalog.calculations.calculate_daily_intraday_range",
        formula="high/low-1", availability="After close", causality="Completed bars only",
        parameters={}, status=CatalogStatus.DISCOVERED, version=1,
    )
    signal = SignalDefinition(
        signal_id="SIG-PRICE", name="Range signal", description="Daily range threshold",
        information_family="PRICE", tags=("range",), factor_ids=(factor.factor_id,),
        embedded_factor=False, provider="synthetic", implementation="fixture.signal",
        rule="range > threshold", states=("active", "inactive"), parameters={"threshold": 0.1},
        availability="After close", causality="Completed bars only", status=CatalogStatus.READY,
        version=1,
    )
    for name, items in (("information_families.json", [family]),
                        ("factors/definitions.json", [factor]),
                        ("signals/definitions.json", [signal])):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "items": [item.to_dict() for item in items]}),
                        encoding="utf-8")
    # Every rejection starts from an admitted catalog, changing only its target field.
    assert CatalogRegistry(tmp_path).show(factor.factor_id)["version"] == 1
    return tmp_path


def test_catalog_is_queryable_and_strict(minimal_catalog) -> None:
    catalog = CatalogRegistry(minimal_catalog)
    assert len(catalog.digest) == 64
    assert catalog.show("F-PRICE")["information_family"] == "PRICE"
    assert catalog.list_definitions(kind="factor", family="PRICE", status="DISCOVERED", query="DAILY") == ({
        "kind": "factor", "id": "F-PRICE", "name": "Daily range", "information_family": "PRICE",
        "status": "DISCOVERED", "provider": "project", "version": 1,
    },)
    assert [row["id"] for row in catalog.list_definitions(kind="signal", status="READY")] == ["SIG-PRICE"]
    assert catalog.list_definitions(query="absent") == ()
    with pytest.raises(CatalogValidationError, match="missing fields"):
        FactorDefinition.from_dict({"factor_id": "F-BROKEN"})
    with pytest.raises(CatalogValidationError, match="unknown information family"):
        catalog.list_definitions(family="MISSING")


def test_catalog_loads_only_canonical_definition_documents(minimal_catalog) -> None:
    # Malformed mirrors are decoys: reading them would fail the public loader.
    (minimal_catalog / "factors/noncanonical.json").write_text("invalid json", encoding="utf-8")
    (minimal_catalog / "signals/noncanonical.json").write_text("invalid json", encoding="utf-8")
    catalog = CatalogRegistry(minimal_catalog)
    assert [item.factor_id for item in catalog.factors] == ["F-PRICE"]
    assert [item.signal_id for item in catalog.signals] == ["SIG-PRICE"]


def test_repository_catalog_preserves_definitions_mirrors_and_platform_implementations() -> None:
    catalog = CatalogRegistry(REPO / "catalog")
    assert len(catalog.families) >= 8
    assert len(catalog.factors) >= 10
    assert len(catalog.signals) >= 246
    assert catalog.show("F-PROJECT-ER60")["information_family"] == "TREND_REGIME"
    assert "T-1" in catalog.show("F-PROJECT-ER60")["causality"]
    assert catalog.show("F-PROJECT-BREADTH-BALANCE")["implementation"].endswith(
        "build_weighted_market_breadth_features"
    )
    assert catalog.show("F-TSFRESH-VOLUME-CONTRACTION-FLOOR-20")["status"] == "DEPRECATED"
    assert catalog.show("F-TSFRESH-ABS-RETURN-MAX-60")["information_family"] == "VOLATILITY_RISK"
    assert catalog.show("F-PROJECT-ETF-NAV-PREMIUM")["inputs"] == ["etf_share_size.nav", "etf_share_size.close"]
    assert any(row["id"] == "SIG-CZSC-cxt_bi_base_V230228"
               for row in catalog.list_definitions(kind="signal", family="MARKET_STRUCTURE"))
    migrated = [item for item in catalog.factors
                if item.implementation.startswith("factor_signal_catalog.calculations.")]
    assert len(migrated) == 11
    assert all(item.version == 3 and item.provider == "project" for item in migrated)
    modules = {}
    for kind, definitions in (("factors", catalog.factors), ("signals", catalog.signals)):
        directory = REPO / "catalog" / kind
        canonical = json.loads((directory / "definitions.json").read_text(encoding="utf-8"))["items"]
        assert [item.to_dict() for item in definitions] == canonical
        mirrors = {}
        for path in directory.glob("*.json"):
            if path.name != "definitions.json":
                for payload in json.loads(path.read_text(encoding="utf-8"))["items"]:
                    identity = payload[kind[:-1] + "_id"]
                    if identity in mirrors:
                        assert mirrors[identity] == payload
                    mirrors[identity] = payload
        for item in definitions:
            if "project" not in item.provider.split("+"):
                continue
            payload = item.to_dict()
            assert payload == mirrors[payload[kind[:-1] + "_id"]]
            # DISCOVERED is research readiness, independent of whether code exists.
            # Deprecated historical references remain searchable without importing them.
            if item.status is not CatalogStatus.DEPRECATED:
                module, function = item.implementation.rsplit(".", 1)
                if module not in modules:
                    modules[module] = import_module(module)
                assert callable(getattr(modules[module], function))


@pytest.mark.parametrize("kind", ["factor", "signal"])
@pytest.mark.parametrize("implementation", [
    "experiments/S005/run.py", "research/S007/features.py",
    r"D:\CodeBase\czsc_trader\experiments\S005\run.py",
    "research.S007.features.calculate", "Experiments/S005/run.py",
])
def test_catalog_rejects_research_owned_implementations(minimal_catalog, kind, implementation):
    canonical = minimal_catalog / (kind + "s") / "definitions.json"
    document = json.loads(canonical.read_text(encoding="utf-8"))
    document["items"][0]["implementation"] = implementation
    canonical.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="must not depend on research"):
        CatalogRegistry(minimal_catalog)
