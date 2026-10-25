"""Observation-only revisions keep trading source and frozen-origin contracts."""
import ast
from dataclasses import replace
import json
import shutil
from types import SimpleNamespace

import pytest
from strategy_runtime import StrategyCandidate, implementation_sha256
from strategy_manager import freeze_contracts as f
from strategy_manager import StrategyRegistry
from czsc_trader.application import validate_frozen_observation_upgrade, validate_release_package
from test_current_contracts import (
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


def test_observation_upgrade_authenticates_source_definition_and_explicit_selection(observation_candidate):
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


@pytest.mark.parametrize("change", ["parameters", "trading_source", "source_hash", "family"])
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
    elif change == "source_hash":
        payload["runtime"]["source_sha256"] = "f" * 64
    else:
        original = replace(original, strategy_id="S901")
    changed = StrategyCandidate("S900", "C9877", payload, candidate.source_root)
    with pytest.raises(ValueError, match="parameters|trading source|hash differs|family differs"):
        validate_frozen_observation_upgrade(context, original, changed)


def test_observation_upgrade_stages_new_binding_and_preserves_frozen_history(observation_candidate, monkeypatch):
    from czsc_trader.application import runtime_migration as m, research_evidence as e
    from test_frozen_runtime_upgrade import _inspected_migration_release, _bytes

    context, original, candidate = observation_candidate
    after = validate_frozen_observation_upgrade(context, original, candidate)
    manifest, binding, source = validate_release_package(context, "S900-v1")
    stored = StrategyRegistry(context.strategy_root).get_version("S900", "v1")
    ref = f.ResearchEvidenceRef(f.ResearchEvidenceOwner("S900", "EX001_20261020"), "a.json", "a" * 64)
    subject = f.FrozenObservationUpgradeSelectionSubject(original, f.CandidateKey("S900", "C9877"), "b" * 64, (ref,))
    new_binding = {**binding, "observation_sha256": after.observation.sha256}
    release = _inspected_migration_release(context, ref.owner, stored, candidate, manifest, new_binding, source)
    report = SimpleNamespace(plan=SimpleNamespace(sha256="b" * 64), release=release, selection=ref)
    # Only the completed-inspection boundary is supplied; publication, binding
    # authentication, original CAS, archival and version preservation stay real.
    monkeypatch.setattr(m, "_upgrade_inputs", lambda *args: (report, candidate, stored, manifest, binding, source))
    monkeypatch.setattr(e, "read_decision", lambda *args: SimpleNamespace(subject=subject))
    request = m.FrozenRuntimeUpgradeRequest(original, subject.candidate, ref, ref, context.root / ".tmp/prepared")
    before = _bytes(context.strategy_root)
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    assert _bytes(context.strategy_root) == before
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    assert receipt.status.value == "COMMITTED"
    _, installed, _ = validate_release_package(context, "S900-v1")
    assert installed["observation_sha256"] == after.observation.sha256 != binding["observation_sha256"]
    current = StrategyRegistry(context.strategy_root).get_version("S900", "v1")
    old_fields, new_fields = stored.to_dict(), current.to_dict()
    for name in ("strategy_payload", "release_hash"):
        old_fields.pop(name)
        new_fields.pop(name)
    assert old_fields == new_fields
    assert m.apply_frozen_runtime_upgrade(context, prepared) == receipt


def test_observation_comparison_only_excludes_declared_added_fields():
    import pandas as pd
    from czsc_trader.application.research_evidence import _observation_comparison, _migration_frame_equal

    definition = SimpleNamespace(observation=SimpleNamespace(signal_panel=SimpleNamespace(evidence_fields=("obs_score",))))
    old = pd.DataFrame({"target": [1.0], "cash": [100.0]})
    new = old.assign(obs_score=0.2)
    _migration_frame_equal(old, _observation_comparison(old, new, definition), {})
    with pytest.raises(ValueError, match="undeclared"):
        _observation_comparison(old, new.assign(obs_unknown=1), definition)
    with pytest.raises(ValueError, match="dates/rows differ"):
        _observation_comparison(old, new.iloc[0:0], definition)
    with pytest.raises(ValueError, match="values differ"):
        _migration_frame_equal(old, _observation_comparison(old, new.assign(cash=101.0), definition), {})


def test_observation_ledger_identity_mapping_preserves_cycle_economics_and_links():
    import pandas as pd
    from czsc_trader.application.research_evidence import _migration_frame_equal

    original = {"cycle_id": "1" * 64, "opening_signal_identity": "2" * 64,
                "allocation_fraction": "1", "cash_budget": "100000", "target_quantity": 200,
                "buy_cost_including_fees": "1000", "phase": "ACTIVE"}
    revised = {**original, "cycle_id": "3" * 64, "opening_signal_identity": "4" * 64}
    before = pd.DataFrame({"cycle_id": [original["cycle_id"]],
                           "signal_identity": [original["opening_signal_identity"]],
                           "entry_cycle_after": [json.dumps(original)]})
    after = pd.DataFrame({"cycle_id": [revised["cycle_id"]],
                          "signal_identity": [revised["opening_signal_identity"]],
                          "entry_cycle_after": [json.dumps(revised)]})
    links = {}
    _migration_frame_equal(before, after, links, observation_upgrade=True)
    with pytest.raises(ValueError, match="economic facts differ"):
        _migration_frame_equal(before, after.assign(entry_cycle_after=json.dumps({**revised, "cash_budget": "100001"})),
                               links, observation_upgrade=True)
    with pytest.raises(ValueError, match="linkage differs"):
        _migration_frame_equal(before, after.assign(entry_cycle_after=json.dumps({**revised, "cycle_id": "5" * 64})),
                               links, observation_upgrade=True)
    # A later ledger must retain the exact same cycle mapping.
    with pytest.raises(ValueError, match="linkage differs"):
        _migration_frame_equal(pd.DataFrame({"entry_cycle_id": [original["cycle_id"]]}),
                               pd.DataFrame({"entry_cycle_id": ["6" * 64]}), links, observation_upgrade=True)


def test_source_allowance_does_not_hide_unrelated_observation_arguments():
    from czsc_trader.application.runtime_migration import _trading_source_tree

    source = '''class Example:
    def __init__(self):
        self.helper = make_trade_helper(observation=1)
        self._definition = StrategyDefinition(observation=ObservationDefinition((), ()))
'''
    assert _trading_source_tree(source, "Example") != _trading_source_tree(
        source.replace("observation=1", "observation=2"), "Example")
    assert _trading_source_tree(source, "Example") == _trading_source_tree(
        source.replace("ObservationDefinition((), ())", "self.observation_definition()"), "Example")
    with pytest.raises(ValueError, match="one explicit"):
        _trading_source_tree(source + '\n        self.other = StrategyDefinition(observation=None)\n', "Example")
