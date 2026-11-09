import json
import pytest
from strategy_manager import (
    StrategyRegistry,
    StrategyFamily,
    RegistryError,
    ValidationError,
)

@pytest.mark.parametrize('schema', [
    pytest.param(1, id='SM-13-C03'),
    pytest.param(2, id='SM-13-C04'),
    pytest.param(3, id='SM-13-C05'),
    pytest.param(4, id='SM-13-C06'),
])
@pytest.mark.risk_cases('SM-13-C03', 'SM-13-C04', 'SM-13-C05', 'SM-13-C06')
def test_registry_rejects_retired_release_and_preserves_original(tmp_path, schema):
    registry = StrategyRegistry(tmp_path)
    path = tmp_path / "S900/versions/v1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": schema}))
    before = path.read_bytes()
    with pytest.raises(RegistryError, match="schema_version must be 5"):
        registry.get_version("S900", "v1")
    assert path.read_bytes() == before


@pytest.mark.risk_cases('SM-03-C04')
def test_SM_03_C04_family_name_collision_preserves_original(tmp_path):
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
    assert registry.get_family("S900") == family
