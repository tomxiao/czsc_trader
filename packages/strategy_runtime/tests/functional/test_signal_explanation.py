"""Explanation declarations bind to actual facts, including versioned read-only history."""
from dataclasses import replace
import json

import pytest
from strategy_runtime import (
    EvidenceGuide, GuideValueRef, ObservationDefinition, ObservationFormat,
    ObservationUnavailable, RuntimeContractError, SeriesValueRef, SignalBasisDefinition,
    SignalExplanationCase, SignalExplanationDefinition, SignalGroup, SignalPanelDefinition,
    SignalStateDefinition, SignalStateOption, SignalSeriesDefinition, SignalText, StateValueRef,
    StrategyObservation, materialize_observation, observe_execution_plan,
)
from test_observation_contract import observed_plan


def text(*parts):
    return SignalText(parts)


def panel():
    return SignalPanelDefinition(
        (SignalGroup('score', '压力', '分', '策略得分', ObservationFormat.NUMBER, 3),),
        (SignalSeriesDefinition('score', '得分', 'score', 'score',
             status_field='obs_status', reason_field='obs_reason',
             guides=(EvidenceGuide('exit', '退出门槛', 'exit'),)),),
        (SignalStateDefinition('decision', '判断', 'obs_decision', (
            SignalStateOption('wait', '等待'), SignalStateOption('exit', '退出'))),),
        SignalExplanationDefinition('decision', tuple(
            SignalExplanationCase(key, text('当前：', StateValueRef('decision')),
                (SignalBasisDefinition('score', text('得分 ', SeriesValueRef('score'),
                    '；门槛 ', GuideValueRef('score', 'exit'))),),
                text('关注门槛 ', GuideValueRef('score', 'exit')),
                text('得分不是上涨概率。门槛 ', GuideValueRef('score', 'exit')))
            for key in ('wait', 'exit'))),
    )


def make(evidence=None, declared=None):
    defaults = dict(score=.31, exit=.08, reason='fixture', active=False, count=2,
                    obs_decision='exit', obs_status='AVAILABLE', obs_reason=None)
    defaults.update(evidence or {})
    return observed_plan(defaults, signal_panel=declared or panel())


def test_explanation_materializes_parameter_facts_and_roundtrips_without_live_definition():
    definition, plan = make()
    observed = materialize_observation(definition, plan)
    explanation = observed.signal_panel.explanation
    assert explanation.judgment == '当前：退出'
    assert explanation.basis[0].text == '得分 0.310 分；门槛 0.080 分'
    assert observed.to_dict()['contract_version'] == 'strategy_observation.v4'
    assert StrategyObservation.from_dict(json.loads(json.dumps(observed.to_dict()))) == observed
    declared = definition.observation
    assert ObservationDefinition.from_dict(declared.to_dict()) == declared
    new_definition, new_plan = make({'exit': .09})
    new_observed = materialize_observation(new_definition, new_plan)
    assert '0.090' in new_observed.signal_panel.explanation.next_watch
    assert '0.090' in new_observed.signal_panel.explanation.explanation
    assert '0.080' in explanation.next_watch


@pytest.mark.parametrize('reference', [StateValueRef('unknown'), SeriesValueRef('unknown'),
                                       GuideValueRef('score', 'unknown')])
def test_undeclared_reference_rejected_at_declaration(reference):
    current = panel()
    bad_case = replace(current.explanation.cases[0], judgment=text(reference))
    with pytest.raises(RuntimeContractError, match='undeclared'):
        replace(current, explanation=replace(current.explanation,
                cases=(bad_case, current.explanation.cases[1])))


def test_all_selector_states_require_unique_cases():
    current = panel()
    with pytest.raises(RuntimeContractError, match='exactly cover'):
        replace(current, explanation=replace(current.explanation, cases=current.explanation.cases[:1]))
    with pytest.raises(RuntimeContractError, match='duplicate'):
        replace(current.explanation, cases=current.explanation.cases * 2)


@pytest.mark.parametrize('evidence', [dict(obs_decision='undeclared'),
    dict(obs_status='UNAVAILABLE', obs_reason='缺少输入'), dict(score=None),
    {'_observation_error': 'observation hook failed'}])
def test_observation_failures_are_explicit_and_leave_validated_plan_unchanged(evidence):
    definition, plan = make(evidence)
    result = observe_execution_plan(definition, plan)
    assert isinstance(result, ObservationUnavailable)
    assert result.contract_version == 'strategy_observation.v4'
    assert 'signal_panel' not in result.to_dict()
    assert plan.action == 'WAIT' and plan.target_position == 0.0
    with pytest.raises(RuntimeContractError):
        materialize_observation(definition, plan)


def test_identity_failure_is_never_downgraded():
    definition, plan = make()
    with pytest.raises(RuntimeContractError, match='differs from runtime'):
        observe_execution_plan(replace(definition, release_hash='e' * 64), plan)


def test_inactive_fact_is_explicit_not_zero():
    definition, plan = make({'obs_status': 'INACTIVE', 'score': .31})
    observed = materialize_observation(definition, plan)
    assert observed.signal_panel.explanation.basis[0].text == '得分 不适用；门槛 不适用'


def test_contract_versions_cannot_silently_add_or_drop_explanation():
    definition, plan = make()
    for model, data in [(ObservationDefinition, definition.observation.to_dict()),
                        (StrategyObservation, materialize_observation(definition, plan).to_dict())]:
        data['contract_version'] = 'strategy_observation.v3'
        with pytest.raises(RuntimeContractError, match='contract version'):
            model.from_dict(data)
        data['contract_version'] = 'strategy_observation.v4'
        del data['signal_panel']['explanation']
        with pytest.raises(RuntimeContractError, match='contract version'):
            model.from_dict(data)
        data['contract_version'] = 'strategy_observation.v3'
        assert model.from_dict(data).to_dict() == data
    old_definition, old_plan = observed_plan()
    assert old_definition.observation.to_dict()['contract_version'] == 'strategy_observation.v2'
    assert StrategyObservation.from_dict(materialize_observation(old_definition, old_plan).to_dict())


def test_snapshot_selector_tampering_is_rejected():
    definition, plan = make()
    data = materialize_observation(definition, plan).to_dict()
    data['signal_panel']['explanation']['case_key'] = 'wait'
    with pytest.raises(RuntimeContractError, match='differs from recorded state'):
        StrategyObservation.from_dict(data)
