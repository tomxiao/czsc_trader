from pathlib import Path
import json
import pytest
from strategy_manager import (
    StrategyRegistry,
    StrategyFamily,
    RegistryError,
    ValidationError,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("schema", [1, 2, 3, 4, True, "5", None])
def test_registry_rejects_retired_release_and_preserves_original(tmp_path, schema):
    registry = StrategyRegistry(tmp_path)
    path = tmp_path / "S900/versions/v1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": schema}))
    before = path.read_bytes()
    with pytest.raises(RegistryError, match="schema_version must be 5"):
        registry.get_version("S900", "v1")
    assert path.read_bytes() == before


def test_retired_writers_and_models_are_unavailable():
    import strategy_manager as sm

    assert not any(name.startswith("_legacy_") for name in dir(StrategyRegistry))
    for name in (
        "append_governance_seal",
        "create_frozen_version_from_credential",
        "record_legacy_governance_acceptance",
    ):
        assert not hasattr(StrategyRegistry, name)
    for name in (
        "CandidateSnapshot",
        "EvaluationMandate",
        "AdjudicationReport",
        "FreezeReviewCase",
        "FreezeApproval",
    ):
        assert name not in sm.__all__ and not hasattr(sm, name)


def test_family_registration_still_validates_names_and_identity(tmp_path):
    registry = StrategyRegistry(tmp_path)
    raw = {
        "schema_version": 2,
        "strategy_id": "S900",
        "name": "test family",
        "scope": ["588080.SH"],
        "research_intent": {"objective": "test"},
        "research_state": "RESEARCHING",
        "created_at": "2026-10-01T10:00:00+08:00",
        "created_by": "tester",
        "updated_at": "2026-10-01T10:00:00+08:00",
    }
    family = StrategyFamily.from_dict(raw)
    registry.create_family(family, actor="tester", reason="authorized")
    assert registry.get_family("S900") == family
    assert registry.validate_all()["strategies"] == 1
    with pytest.raises((RegistryError, ValidationError)):
        registry.create_family(
            StrategyFamily.from_dict({**raw, "strategy_id": "S901"}),
            actor="tester",
            reason="duplicate name",
        )
