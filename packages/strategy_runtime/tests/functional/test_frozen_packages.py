"""Current real frozen packages load and preserve account execution semantics."""
from dataclasses import fields, replace
from pathlib import Path
from datetime import date

import pytest
import pandas as pd
from dataflows import Dataflows, DataSpace, Dataset, ProviderBinding, ProviderConfig, PreparePolicy

from strategy_manager import StrategyRegistry
from strategy_runtime import (
    StrategyIdentity,
    StrategyCandidate,
    StrategyDefinition,
    StrategyRelease,
    StrategyRuntime,
    materialize_observation,
    EvidenceGuide,
    ObservationFormat,
    ObservationValueType,
    SignalAvailability,
    StrategyInit,
    TradableWindow,
)
from strategy_runtime.contracts import signal_identity_for, plan_identity_for
from test_observation_contract import observed_plan

ROOT = Path(__file__).resolve().parents[4] / "strategies"
LEGACY_RELEASE_HASHES = {
    "S001-v1": "57d7f97f1fa8a7d5dafdf1562d83f772664aaedff95d12a4f95b391be4b0d4d6",
    "S001-v2": "fc0c16b6fe91dce796278bfccae3e828a79efd08e765205ccec8b71c945a86e7",
    "S007-v1": "6d1d5dd533dd02a1117b4a703e37d690a7ed711fc78d229b452bd1f9bf2dbeaa",
}
pytestmark = pytest.mark.release_acceptance


def archived_legacy_root(release_id):
    return ROOT / "revisions" / release_id / LEGACY_RELEASE_HASHES[release_id] / "strategies"



def test_real_package_behavior_is_independent_of_candidate_or_release_identity(loaded_release):
    record, deployment, release, _ = loaded_release
    family, _ = record.release_id.split("-")
    from strategy_runtime.equity_definition import EquityStrategyCandidate
    if isinstance(release, EquityStrategyCandidate):
        candidate = EquityStrategyCandidate(family, 'C0001', release.definition, deployment.source_root)
        assert candidate.content_identity == release.content_identity
        from strategy_runtime import canonical_sha256
        assert canonical_sha256(candidate.payload) == canonical_sha256(record.strategy_payload)
        assert candidate.candidate_id != release.candidate_id == deployment.runtime_candidate_id
        assert candidate.definition.contract_version == 4
        assert record.schema_version == 5
        assert record.release_hash == deployment.release_hash
        assert not {'origin', 'governance', 'governance_hash'} & record.to_dict().keys()
        assert not any(name.startswith('charts/') for name in deployment.install_files)
        return
    candidate = StrategyRuntime().describe(
        StrategyCandidate(family, "C0001", record.strategy_payload, deployment.source_root)
    )
    for field in fields(StrategyDefinition):
        assert getattr(candidate, field.name) == getattr(release, field.name)
    assert candidate.identity_kind == "CANDIDATE"
    assert candidate.release_id == f"{family}-C0001"
    assert release.identity_kind == "RELEASE"
    assert release.release_id == record.release_id
    assert record.schema_version == 5
    assert not {"origin", "governance", "governance_hash"} & record.to_dict().keys()
    assert not any(name.startswith("charts/") for name in deployment.install_files)
    assert release.schema_version == 3
    assert release.observation.sha256 == deployment.binding.spec.observation_sha256


@pytest.mark.parametrize("release_id", ("S001-v1", "S001-v2"))
def test_real_rebindable_package_uses_parameter_factory(release_id):
    family, version = release_id.split("-")
    archived = archived_legacy_root(release_id)
    record = StrategyRegistry(archived).get_version(family, version)
    runtime = StrategyRuntime(strategy_root=archived)
    release = StrategyRelease.from_mapping(record.to_dict())
    original = runtime.describe(release)
    rebound = runtime.describe(release, symbol="510500.SH")
    assert rebound.tradable_symbol == "510500.SH"
    assert rebound.parameters == original.parameters
    assert rebound.release_hash == original.release_hash
    assert rebound.release_id == original.release_id


def test_s007_declares_segmented_requests_for_the_full_2026_backtest_window(tmp_path):
    archived = archived_legacy_root("S007-v1")
    record = StrategyRegistry(archived).get_version('S007', 'v1')

    def calendar(request):
        dates = pd.date_range(request.start, request.end)
        opened = (dates.dayofweek < 5) & ~dates.isin(pd.to_datetime(['2026-01-01', '2026-01-02']))
        return pd.DataFrame({'Date': dates, 'IsOpen': opened.astype(int)}), {'vendor': 'fixture'}

    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('assets')), providers=ProviderConfig({
        Dataset.TRADING_CALENDAR: ProviderBinding('fixture', '1', calendar),
    }))
    strategy = StrategyRuntime(archived, dataflows=flows).create(StrategyInit(
        StrategyRelease.from_mapping(record.to_dict()),
        TradableWindow(date(2026, 1, 5), date(2026, 9, 30)), tmp_path / 'context',
    ))
    request = strategy.calendar_request()
    prepared = flows.prepare((request,), policy=PreparePolicy.REUSE)
    plan = strategy.plan_inputs(flows.fetch(request, prepared=prepared.reference))
    assert min(plan.signal_dates.values()) == date(2025, 12, 31)
    for name in ('incremental_shibor_daily', 'incremental_chinext_daily_basic', 'incremental_etf_share_size'):
        assert plan.requests[name].start == '2026-08-06'
    assert plan.requests['incremental_spx_daily'].start == '2026-07-30'
    assert plan.requests['incremental_chinext_daily_basic'].coverage.minimum_sessions == 20
    assert plan.requests['incremental_chinext_daily_basic'].coverage.observations_through == '2026-09-03'
    assert plan.requests['incremental_etf_share_size'].coverage.observations_through == '2026-09-02'
    assert plan.requests['feature_seed'].end == '2026-09-02'
    assert plan.requests['feature_seed'].coverage is None


def test_current_observation_uses_declared_fields_and_current_identity(loaded_release):
    _, _, actual, _ = loaded_release
    from strategy_runtime.equity_definition import EquityStrategyCandidate
    if isinstance(actual, EquityStrategyCandidate):
        from strategy_runtime.account_strategy import AccountDecision
        from strategy_runtime.signal_explanation import SignalExplanationSnapshot
        # Native V4 declares target explanation cases instead of legacy panels.
        # Materialize all declared cases with explicit recorded facts, as below.
        observed = []
        for target in (0., 1.):
            decision = AccountDecision.from_facts(target, 'Synthetic declared target',
                facts={'symbol': actual.instrument.symbol, 'target': target}, next_watch='Next declared decision')
            explanation = SignalExplanationSnapshot.from_dict(decision.explanation.to_dict())
            assert explanation == decision.explanation
            assert explanation.state_key == 'target' and explanation.basis
            observed.append(explanation.case_key)
        assert tuple(observed) == actual.definition.explanation_cases
        return
    _, template = observed_plan()
    strategy = StrategyIdentity(actual.strategy_family_id, actual.release_id, actual.release_hash,
                                actual.runtime_sha256, actual.tradable_symbol)
    signal = signal_identity_for(strategy=strategy, signal_date=template.signal_date,
                                 target_position=template.target_position,
                                 input_identities=template.input_identities,
                                 price_identities=template.price_identities)
    evidence = {series.value_field: 0.3 for series in actual.observation.series}
    for series in actual.observation.series:
        for guide in series.guides:
            if hasattr(guide, "value_field"):
                evidence[guide.value_field] = 0.2
    values = {
        ObservationValueType.NUMBER: 0.3, ObservationValueType.INTEGER: 1,
        ObservationValueType.BOOLEAN: True, ObservationValueType.TEXT: "synthetic reason",
    }
    evidence.update({fact.value_field: values[fact.value_type] for fact in actual.observation.facts})
    panel = actual.observation.signal_panel
    if panel is not None:
        # This test materializes declared fields; the execution-path tests cover
        # the strategy's observation hook. Supply v4 panel evidence as well as
        # the original series/facts, without deriving a business judgment here.
        formats = {group.key: group.format for group in panel.groups}
        for series in panel.series:
            value = 1 if formats[series.group] is ObservationFormat.INTEGER else 0.3
            evidence[series.value_field] = value
            if series.segment_field is not None:
                evidence[series.segment_field] = "synthetic-segment"
            for guide in series.guides:
                if isinstance(guide, EvidenceGuide):
                    evidence[guide.value_field] = value
        for state in panel.states:
            evidence[state.value_field] = state.options[0].key
        for item in (*panel.series, *panel.states):
            if item.status_field is not None:
                evidence[item.status_field] = SignalAvailability.AVAILABLE.value
            if item.reason_field is not None:
                evidence[item.reason_field] = "synthetic availability reason"
        assert set(panel.evidence_fields) <= evidence.keys()
    identity = plan_identity_for(signal_identity=signal, actual_quantity=template.actual_quantity,
                                 target_quantity=template.target_quantity,
                                 cycle_target_quantity=template.cycle_target_quantity,
                                 plan_mode=template.plan_mode, capital_mode=template.capital_mode,
                                 allocation_fraction=template.allocation_fraction,
                                 orders=template.orders, legs=template.legs)
    plan = replace(template, strategy=strategy, symbol=actual.tradable_symbol,
                   signal_identity=signal, plan_identity=identity, evidence=evidence)
    facts = materialize_observation(actual, plan)
    assert facts.strategy == strategy
    assert len(facts.series) == len(actual.observation.series)
    assert len(facts.facts) == len(actual.observation.facts)
    if panel is not None:
        assert facts.signal_panel.groups == panel.groups
        assert len(facts.signal_panel.series) == len(panel.series)
        assert len(facts.signal_panel.states) == len(panel.states)
        for declared, observed in zip(panel.series, facts.signal_panel.series, strict=True):
            assert observed.key == declared.key
            assert observed.value == evidence[declared.value_field]
            assert observed.status is SignalAvailability.AVAILABLE
            assert observed.reason is None
            assert observed.segment_id == (evidence[declared.segment_field] if declared.segment_field else None)
            for guide, observed_guide in zip(declared.guides, observed.guides, strict=True):
                assert observed_guide.value == (evidence[guide.value_field] if isinstance(guide, EvidenceGuide) else guide.value)
        for declared, observed in zip(panel.states, facts.signal_panel.states, strict=True):
            assert observed.key == declared.key
            assert observed.value == evidence[declared.value_field]
            assert observed.status is SignalAvailability.AVAILABLE
            assert observed.reason is None
        if panel.explanation is not None:
            selector = next(state for state in panel.states if state.key == panel.explanation.state_key)
            explanation = facts.signal_panel.explanation
            assert explanation.state_key == selector.key
            assert explanation.case_key == evidence[selector.value_field]
            case = next(case for case in panel.explanation.cases if case.key == explanation.case_key)
            assert [basis.key for basis in explanation.basis] == [basis.key for basis in case.basis]
