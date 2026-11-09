# Risk ownership: TDR-19 TDR-24
"""Observation-only revisions keep trading source and frozen-origin contracts."""
import ast
from dataclasses import replace
import json
import shutil
from types import SimpleNamespace

import pytest
from strategy_runtime import StrategyCandidate, implementation_sha256
from strategy_manager import freeze_contracts as f
from czsc_trader.application import validate_frozen_observation_upgrade, validate_release_package
from frozen_contract_support import (
    current_frozen as current_frozen, inspection as inspection,
    managed_evaluation as managed_evaluation,
)


@pytest.fixture
def observation_candidate(current_frozen):
    context, stored = current_frozen
    manifest, _, source = validate_release_package(context, "S900-v1")
    original = f.FrozenVersionReference("S900", "v1", stored.release_hash, manifest["package_hash"])
    target = context.root / ".tmp/observation-source/strategy_runtime"
    shutil.copytree(source, target)
    payload = json.loads(json.dumps(dict(stored.strategy_payload), default=dict))
    path = target / payload["runtime"]["source_files"][0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    kw = next(n for n in ast.walk(init) if isinstance(n, ast.keyword) and n.arg == "observation")
    old = ast.unparse(kw.value)
    kw.value = ast.parse("self.observation_definition()", mode="eval").body
    cls.body.extend(ast.parse(f'''
def observation_definition(self):
    from dataclasses import replace
    from strategy_runtime import SignalPanelDefinition, SignalGroup, SignalSeriesDefinition
    return replace({old}, signal_panel=SignalPanelDefinition(
        (SignalGroup("condition", "Condition", "ratio", "fixture"),),
        (SignalSeriesDefinition("score", "Score", "condition", "obs_score"),)))
def observation_history(self, inputs, context, history):
    return pd.DataFrame({{"obs_score": history["fixture_signal"]}}, index=history.index)
''').body)
    path.write_text(ast.unparse(ast.fix_missing_locations(tree)) + '\n', encoding="utf-8")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=target)
    return context, original, StrategyCandidate("S900", "C9877", payload, target)


def test_TDR_24_C01_observation_upgrade_authenticates_source_definition_and_explicit_selection(observation_candidate):
    context, original, candidate = observation_candidate
    after = validate_frozen_observation_upgrade(context, original, candidate)
    assert after.observation.signal_panel is not None
    evidence = f.ResearchEvidenceRef(f.ResearchEvidenceOwner("S900", "EX001_20261020"), "a.json", "a" * 64)
    subject = f.FrozenObservationUpgradeSelectionSubject(original, f.CandidateKey("S900", "C9877"), "b" * 64, (evidence,))
    decision = f.ResearchDecision("observation_upgrade", "S900", f.DecisionAction.APPROVE,
                                 subject, evidence, "Synthetic observation-only selection")
    restored = f.ResearchDecision.from_dict(decision.to_dict())
    assert restored == decision
    assert type(restored.subject) is f.FrozenObservationUpgradeSelectionSubject
    assert context.strategy_root.joinpath("S900/versions/v1.json").is_file()


@pytest.mark.parametrize('change', [pytest.param('parameters', id='TDR-24-C02')])
def test_observation_upgrade_rejects_changes_outside_display_scope(observation_candidate, change):
    context, original, candidate = observation_candidate
    payload = json.loads(json.dumps(dict(candidate.payload), default=dict))
    if change == "parameters":
        payload["parameters"] = {**payload["parameters"], "threshold": 0.9}
    elif change == "trading_source":
        path = candidate.source_root / payload["runtime"]["source_files"][0]
        path.write_text(path.read_text(encoding="utf-8") + '\nTRADING_SIDE_EFFECT = 1\n', encoding="utf-8")
        payload["runtime"]["source_sha256"] = implementation_sha256(
            tuple(payload["runtime"]["source_files"]), source_root=candidate.source_root)
    elif change == "non_observation_sidecar":
        name = "trading_helper.py"
        (candidate.source_root / name).write_text("TRADING_RULE = 1\n", encoding="utf-8")
        payload["runtime"]["source_files"].append(name)
        payload["runtime"]["source_sha256"] = implementation_sha256(
            tuple(payload["runtime"]["source_files"]), source_root=candidate.source_root)
    elif change == "source_hash":
        payload["runtime"]["source_sha256"] = "f" * 64
    else:
        original = replace(original, strategy_id="S901")
    changed = StrategyCandidate("S900", "C9877", payload, candidate.source_root)
    with pytest.raises(ValueError, match="parameters|trading source|non-observation|hash differs|family differs"):
        validate_frozen_observation_upgrade(context, original, changed)




def test_TDR_19_C06_observation_comparison_only_excludes_each_sides_declared_fields():
    import pandas as pd
    from czsc_trader.application.research_evidence import _observation_comparison, _migration_frame_equal

    definition = SimpleNamespace(observation=SimpleNamespace(signal_panel=SimpleNamespace(evidence_fields=("obs_score",))))
    legacy = SimpleNamespace(observation=SimpleNamespace(signal_panel=None))
    old = pd.DataFrame({"target": [1.0], "cash": [100.0]})
    new = old.assign(obs_score=0.2)
    _migration_frame_equal(*_observation_comparison(old, new, legacy, definition), {})
    _migration_frame_equal(*_observation_comparison(new, old.assign(obs_score=0.3), definition, definition), {})
    renamed = SimpleNamespace(observation=SimpleNamespace(signal_panel=SimpleNamespace(evidence_fields=("obs_new",))))
    _migration_frame_equal(*_observation_comparison(new, old.assign(obs_new=0.4), definition, renamed), {})
    with pytest.raises(ValueError, match="undeclared"):
        _observation_comparison(old, new.assign(obs_unknown=1), legacy, definition)
    with pytest.raises(ValueError, match="undeclared"):
        _observation_comparison(new, new, legacy, definition)
    with pytest.raises(ValueError, match="dates/rows differ"):
        _observation_comparison(old, new.iloc[0:0], legacy, definition)
    with pytest.raises(ValueError, match="values differ"):
        _migration_frame_equal(*_observation_comparison(old, new.assign(cash=101.0), legacy, definition), {})
    with pytest.raises(ValueError, match="shape/dates differ"):
        _migration_frame_equal(*_observation_comparison(old, new.drop(columns="cash"), legacy, definition), {})
