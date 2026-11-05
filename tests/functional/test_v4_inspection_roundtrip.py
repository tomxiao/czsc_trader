"""Native V4 final packages and dual-market inspection, on synthetic data only."""
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from dataflows import MarketId, EquityProduct, TimeInterval
from strategy_runtime import InspectionControl, StrategyComputation
from strategy_runtime.deployment import validate_release_package
from strategy_manager import CandidateEvidence, StrategyRegistry, freeze_contracts as f
from czsc_trader.application import (CandidateInspectionRequest, EquityInspectionReplay,
    EquityInspectionProtocol, FreezeTarget, InspectionDataKind, inspect_candidate,
    freeze_candidate, get_freeze_result, record_research_decision, describe_inspection_environment)
from czsc_trader.application.equity_inspection import replay_account
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import ResearchExecutionSession
from paper_trading_engine.equity_inspection import (EquityPteDecision, EquityPteReport,
    EquityPteRestart, EquityPteReconcile, EquityPteScenario, EquityPteInspectionProtocol)
from test_equity_adjusted_observations import setup_adjusted
from test_equity_inspection_roundtrip import seed_registered_frozen_candidate


def native_fixture(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP):
    context, request, products, _, _ = setup_adjusted(tmp_path, market, computation)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        request = context.evaluation.prepare(request, execution=execution).request
    replay = EquityInspectionReplay(f.InspectionCoordinate('main', 'standard'), request.input_binding,
        request.requests(context.execution_spec), request.window, request.initial_cash, request.fee_rate)
    return context, request, products, replay


def native_protocol(context, request, products):
    row = products[EquityProduct.BARS].loc[lambda x: x.BarStart == request.window.start].iloc[0]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    quantity = 900 if request.candidate.instrument.market is MarketId.CN else 989
    partial_quantity = context.execution_spec.quantity_step
    cash = Decimal(str(request.initial_cash))
    fee = Decimal(str(request.fee_rate))
    price = Decimal('10')
    partial = EquityPteReport(0, partial_quantity, price, interval.start + timedelta(minutes=1), 'FILLED_PART')
    complete = EquityPteReport(0, quantity, price, interval.start + timedelta(minutes=2), 'FILLED_ALL')
    reconcile = EquityPteReconcile(cash, 0)
    scenarios = [EquityPteScenario('partial-duplicate-restart',
        (reconcile, EquityPteDecision(interval, interval.start), partial, partial, EquityPteRestart(), complete),
        cash - quantity * price * (1 + fee), quantity, Decimal(0))]
    reserved = quantity * Decimal('10.10') * (1 + fee)
    for code, outcome, at in [('REJECTED', 'REJECTED', interval.start),
                              ('UNKNOWN', 'UNKNOWN', interval.start), ('EXPIRED', 'ACCEPTED', interval.end)]:
        scenarios.append(EquityPteScenario(code,
            (reconcile, EquityPteDecision(interval, at, outcome, code)),
            cash if code == 'REJECTED' else cash - reserved, 0, Decimal(0)))
    scenarios.append(EquityPteScenario('reconciliation-blocked',
        (EquityPteReconcile(cash-1, 0), EquityPteDecision(interval, interval.start, expected='RECONCILIATION_BLOCKED')),
        cash, 0, Decimal(0)))
    return EquityInspectionProtocol('candidate-inspection-v4', 'ECONOMIC_V1', 0.,
        EquityPteInspectionProtocol(describe_inspection_environment(context.repository), tuple(scenarios)))


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('computation', [StrategyComputation.STATEFUL_STEP, StrategyComputation.BATCH_HISTORY])
def test_native_technical_replay_preserves_adjusted_inputs_raw_fills_and_state(tmp_path, market, computation, monkeypatch):
    context, request, _, replay = native_fixture(tmp_path, market, computation)
    def forbidden(*args, **kwargs):
        raise AssertionError('native replay must not run the retired V2 accounting audit')
    monkeypatch.setattr('strategy_evaluator.frozen_equity._audit_frozen_equity_account', forbidden)
    facts = replay_account(request.candidate, context.data, replay)
    assert facts['input']['runtime_kind'] == 'ACCOUNT_REPLAY'
    assert facts['definition']['contract_version'] == 4
    assert facts['final_state']['revision'] == 3
    assert facts['facts']['fills'] and all(x['price'] < 11 for x in facts['facts']['fills'])
    assert facts['source'][request.candidate.definition.auxiliary_inputs[0].data_key(EquityProduct.BARS)][0]['Close'] == 20.
    assert facts['source'][request.candidate.definition.auxiliary_inputs[1].data_key(EquityProduct.BARS)][0]['Close'] == 200.


def test_native_technical_replay_rejects_batch_that_changes_in_online_context(tmp_path):
    from strategy_runtime import equity_source_hash
    context, request, _, replay = native_fixture(tmp_path, MarketId.US, StrategyComputation.BATCH_HISTORY)
    source = request.candidate.source_root / 'strategy.py'
    source.write_text("from strategy_runtime import AccountDecision\n"
        "def batch(ctx):\n"
        "    return tuple(AccountDecision.from_facts(float(i%2), 'index dependent', facts={'i':i}, "
        "next_watch='next observation') for i, row in enumerate(ctx.observations))\n", encoding='utf-8')
    candidate = replace(request.candidate, definition=replace(request.candidate.definition,
        source_sha256=equity_source_hash(source.parent, ('strategy.py',))))
    with pytest.raises(ValueError, match='batch decisions differ between historical and online'):
        replay_account(candidate, context.data, replay)


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_native_dual_market_inspection_freezes_exact_v4_package(tmp_path, market):
    context, request, products, replay = native_fixture(tmp_path, market)
    seed_registered_frozen_candidate(context, request)
    repository = context.repository
    registration = StrategyRegistry(repository.research_registry_root).get_candidate_registration(request.candidate.key)
    confirmation = tmp_path / '.tmp/engineering-approval.json'
    confirmation.parent.mkdir(exist_ok=True)
    confirmation.write_text('{"scope":"synthetic engineering fixture only"}', encoding='utf-8')
    source = CandidateEvidence(confirmation.relative_to(tmp_path).as_posix(), sha256(confirmation.read_bytes()).hexdigest())
    selection = record_research_decision(repository, f.ResearchDecision('native-selection', 'S999', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(registration.key, registration.content_sha256, registration.record_sha256), source, 'fixture selection'))
    protocol = native_protocol(context, request, products)
    inspection = CandidateInspectionRequest(registration.key, selection, context, request.experiment,
        FreezeTarget('v1', None, 'native V4 synthetic package', date(2026,10,15), date(2026,10,16)),
        protocol, (replay,), InspectionDataKind.SYNTHETIC)
    wrong = replace(inspection, protocol=replace(protocol, method_version='candidate-inspection-v2'))
    rejected = inspect_candidate(repository, wrong, control=InspectionControl(max_workers=1))
    assert rejected.status is f.InspectionStatus.FAIL and rejected.release is None
    assert 'protocol differs' in rejected.behavior_equivalence.cases[0].summary
    assert validate_inspection(tmp_path, rejected.reference) == rejected
    report = inspect_candidate(repository, inspection, control=InspectionControl(max_workers=1, timeout_seconds=90))
    assert report.status is f.InspectionStatus.PASS, [(x.case_id,x.summary) for g in (report.behavior_equivalence,report.pte_runtime) for x in g.cases]
    assert validate_inspection(tmp_path, report.reference) == report
    approval = record_research_decision(repository, f.ResearchDecision('native-freeze', 'S999', f.DecisionAction.APPROVE,
        f.FreezeSubject(report.origin.candidate, report.origin.content_sha256, report.reference, report.plan.sha256, 'v1'), source, 'approve exact synthetic package'))
    operation = f.FreezeCandidateRequest(f.FreezeRequestId('S999','native-fixture'), report.reference, approval)
    receipt = freeze_candidate(repository, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED
    assert get_freeze_result(repository, operation.request_id) == receipt == freeze_candidate(repository, operation)
    package = validate_release_package(repository.strategy_root, 'S999-v1')
    assert package.package_sha256 == report.release.package_sha256
    assert package.release.payload['runtime']['kind'] == 'ACCOUNT_REPLAY'
    assert package.release.payload['runtime']['contract_version'] == 4
    assert json.loads((package.source_root.parent.parent/'runtime_binding.json').read_text())['observation_sha256']
