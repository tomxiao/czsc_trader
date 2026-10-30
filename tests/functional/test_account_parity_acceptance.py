"""Three-stage acceptance through the public research APIs, not private engines."""
from datetime import date
import json

import pytest
from dataflows import MarketId, BarFrequency
from strategy_runtime import StrategyComputation
from czsc_trader.research_tools import (ResearchExecutionSession, EvaluationEvidenceWrite,
    build_assessment_evidence, AccountRunRef, AccountDiagnosisRequest, EvaluationWindow)
from czsc_trader.application import (publish_evidence, diagnose_accounts, register_candidate,
    CandidateRegistrationRequest, load_candidate)
from account_parity_support import setup_account


@pytest.mark.parametrize('contract', [1,2,3])
def test_retired_research_contracts_are_rejected_at_construction(tmp_path,contract):
    from dataclasses import replace
    context,request=setup_account(tmp_path,MarketId.US,BarFrequency.M30)
    if contract==2:
        candidate=replace(request.candidate,definition=replace(request.candidate.definition,
            contract_version=2,computation=None,feature_graph=None,state_schema=None))
        with pytest.raises(TypeError,match='contract_version=4'):
            replace(request,candidate=candidate)
    else:
        with pytest.raises(ValueError,match='contract'):
            replace(request.candidate.definition,contract_version=contract)


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_parameter_lineage_and_checkpoint_preserve_account_contract(tmp_path, market):
    from dataclasses import replace
    from strategy_runtime import equity_source_hash, ExecutionResources
    from strategy_evaluator import (AssessmentCandidate, ParameterAxis, RealDomain, BoundedLocalStep,
        RelativeChangeLimit, ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest,
        ParameterNeighborhoodSpace, build_parameter_neighborhood_design)
    from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence
    from czsc_trader.research_tools import MaterialEvidenceWrite, ParameterEvaluationPlan, EvaluationLineage
    from czsc_trader.research_tools._equity_checkpoint import encode_result, decode_result

    context, request = setup_account(tmp_path, market, BarFrequency.M30)
    context.evaluation.resources = ExecutionResources(2, 1)
    root = request.candidate.source_root
    (root/'strategy.py').write_text('''from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
def step(ctx,state):
    target = 0. if ctx.account.quantity else ctx.parameters['allocation']
    return AccountStepResult(AccountDecision.from_facts(target,'allocation',facts={'target':target},
        next_watch='next bar'),cycle_values=StateRecord())
''', encoding='utf-8')
    definition = replace(request.candidate.definition,source_sha256=equity_source_hash(root,('strategy.py',)),
        parameters_json='{"allocation":0.5}', parameter_schema_json='{"allocation":{"type":"number","minimum":0.1,"maximum":0.9}}')
    request = replace(request,candidate=replace(request.candidate,definition=definition))
    with ResearchExecutionSession(context,experiment=request.experiment) as execution:
        center = context.evaluation.prepare(request,execution=execution)
        def material(name,value):
            return publish_evidence(context,MaterialEvidenceWrite(request.experiment,name,value,
                'application/json','json'),execution=execution)
        mapping, feasibility = material('mapping',b'{}'), material('feasibility',b'{}')
        design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
            AssessmentCandidate('S999-C0001',definition.content_identity.content_sha256),ParameterNeighborhoodProtocol(),
            ParameterNeighborhoodSpace((ParameterAxis('allocation',.5,RealDomain(.1,.9),
                BoundedLocalStep(RelativeChangeLimit(.05)),('allocation',),'fraction'),),
                mapping.sha256,feasibility.sha256)),feasibility=lambda _:True).design
        children = tuple(context.evaluation.prepare(replace(request,candidate=replace(request.candidate,
            candidate_id=f'C{index+2:04}',definition=replace(definition,
                parameters_json=json.dumps({v.name:v.value for v in point.values})))),execution=execution)
            for index,point in enumerate(design.points))
        plan = ParameterEvaluationPlan.create(design,center,children,mapping_evidence=mapping,
            feasibility_evidence=feasibility,dataflows=context.data,execution=execution)
        assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
        reference = material('plan',json.dumps(plan.to_dict()).encode())
        bound = []
        for index,child in enumerate(children):
            derivation = CandidateDerivation(center.candidate.key,center.candidate.content_identity.content_sha256,
                child.candidate.key,child.candidate.content_identity.content_sha256,CandidateDerivationKind.PARAMETERS,
                {v.name:v.value for v in design.points[index].values},design.protocol.sha256,
                CandidateEvidence(reference.repository_path,reference.sha256))
            bound.append(context.evaluation.prepare(replace(child.request,lineage=EvaluationLineage(derivation,
                plan.bind_point(reference,index,repository_root=context.repository.root))),execution=execution))
        outcomes = context.evaluation.evaluate_many(tuple(bound),execution=execution)
        assert all(item.result is not None for item in outcomes),[item.error for item in outcomes]
        for index,item in enumerate(outcomes):
            facts, = build_assessment_evidence(bound[index],item.result,execution=execution)
            assert facts.parameter_point == design.bind_point(index) and facts.parent == design.center
            checkpoint = encode_result(item.result)
            assert decode_result(checkpoint,item.result.request_hash) == item.result
            with pytest.raises(ValueError,match='V4 artifact closure'):
                decode_result(dict(checkpoint,kind='equity-research/v3'),item.result.request_hash)


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_stage_one_two_daily_plan_uses_real_1130_execution_quote(tmp_path, market):
    from dataclasses import replace
    from strategy_runtime import equity_source_hash, ExecutionInput
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY, gap_kind='checkpoint')
    root = request.candidate.source_root
    (root/'strategy.py').write_text('''from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.replay_contracts import ReplayOrder, ReplayLeg
from strategy_runtime.contracts import OrderSide, OrderType
def step(ctx, state):
    assert 'execution' not in ctx.auxiliary_histories
    if ctx.account.quantity==0:
        decision=AccountDecision.from_facts(1.,'initial core',facts={'q':0},next_watch='next day',
            orders=(ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,10.1),))
    elif ctx.account.sellable_quantity>=100:
        opening=ctx.point.execution_interval.start
        checkpoint=datetime.combine(opening.astimezone(ZoneInfo(ctx.session.timezone)).date(),time(11,30),tzinfo=ZoneInfo(ctx.session.timezone))
        legs=(ReplayLeg(0,ReplayOrder(OrderSide.SELL,100,OrderType.MARKET),'OPEN',opening,opening+timedelta(minutes=1)),
              ReplayLeg(1,ReplayOrder(OrderSide.BUY,100,OrderType.MARKET),'11:30_CLOSE',checkpoint-timedelta(minutes=1),checkpoint,0,'FILLED'))
        decision=AccountDecision.from_facts(1.,'confirmed sell then buy',facts={'q':ctx.account.quantity},next_watch='next day',legs=legs)
    else:
        decision=AccountDecision.from_facts(1.,'wait',facts={'q':ctx.account.quantity},next_watch='next day',capital_mode='full_available_cash')
    return AccountStepResult(decision,cycle_values=StateRecord())
''', encoding='utf-8')
    definition=replace(request.candidate.definition,source_sha256=equity_source_hash(root,('strategy.py',)),session_context=True,
        execution_input=ExecutionInput(request.candidate.instrument, request.sources.bars, BarFrequency.M30))
    request=replace(request,candidate=replace(request.candidate,definition=definition))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        bound=context.evaluation.prepare(request,execution=execution)
        outcome,=context.evaluation.evaluate_many((bound,),execution=execution)
        assert outcome.result is not None,outcome.error
        facts,=build_assessment_evidence(bound,outcome.result,execution=execution)
        ledger=json.loads(facts.equity.candidate_ledger)
        assert ledger['execution_bars']
        from czsc_trader.research_tools.equity_replay import materialize_equity
        quality = materialize_equity(outcome.result).payload['runs']['candidate']['data_quality']
        assert quality['execution_input']['affected_sessions'] == ['2026-10-28']
        assert any(row['reason']=='MISSING_EXECUTION_BAR' for row in quality['affected_orders'])
        selected=[r for r in ledger['fills'] if r['quote_source']=='EXECUTION_BARS']
        assert selected
        from zoneinfo import ZoneInfo
        from datetime import datetime
        assert any(datetime.fromisoformat(r['executed_at']).astimezone(ZoneInfo(request.candidate.instrument.timezone)).strftime('%H:%M')=='11:30'
                   for r in selected)


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_gap_diagnostics_use_instrument_local_dates_and_recover(tmp_path, market):
    from czsc_trader.research_tools.equity_replay import materialize_equity
    context, request = setup_account(tmp_path,market,BarFrequency.M30,gap_kind='day')
    with ResearchExecutionSession(context,experiment=request.experiment) as execution:
        prepared=context.evaluation.prepare(request,execution=execution)
        outcome,=context.evaluation.evaluate_many((prepared,),execution=execution)
        assert outcome.result is not None,outcome.error
        build_assessment_evidence(prepared,outcome.result,execution=execution)
        run=materialize_equity(outcome.result).payload['runs']['candidate']
        assert run['data_quality']['evaluation_window']['affected_sessions']==['2026-10-28']
        assert run['data_quality']['suppressed_signals']>0
        assert any(row['session']=='2026-10-29' and not row['valuation_stale'] for row in run['account_points'])


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_stage_two_multi_order_round_trips_reconcile_public_diagnosis(tmp_path, market):
    from dataclasses import replace
    from strategy_runtime import equity_source_hash
    context, request = setup_account(tmp_path, market, BarFrequency.M30)
    root = request.candidate.source_root
    (root/'strategy.py').write_text('''from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.replay_contracts import ReplayOrder
from strategy_runtime.contracts import OrderSide, OrderType
def step(ctx, state):
    q=ctx.account.quantity
    if q==0:
        decision=AccountDecision.from_facts(.5,'two entry orders',facts={'q':q},next_watch='next bar',
            orders=(ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,10.1),ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,10.1)))
    elif ctx.account.sellable_quantity==q:
        decision=AccountDecision.from_facts(0.,'two exit orders',facts={'q':q},next_watch='next bar',
            orders=(ReplayOrder(OrderSide.SELL,100,OrderType.MARKET),ReplayOrder(OrderSide.SELL,q-100,OrderType.MARKET)))
    else:
        decision=AccountDecision.from_facts(1.,'wait for legal sale',facts={'q':q},next_watch='next bar',capital_mode='full_available_cash')
    return AccountStepResult(decision,cycle_values=StateRecord())
''', encoding='utf-8')
    definition = replace(request.candidate.definition, source_sha256=equity_source_hash(root,('strategy.py',)))
    request = replace(request, candidate=replace(request.candidate,definition=definition))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,),execution=execution)
        assert outcome.result is not None, outcome.error
        facts, = build_assessment_evidence(prepared,outcome.result,execution=execution)
        ledger=json.loads(facts.equity.candidate_ledger)
        assert len(ledger['fills']) > len({r['interval_end'] for r in ledger['fills']})
        assert ledger['trades']
        from strategy_evaluator.equity_diagnosis import diagnose_equity_accounts
        result=diagnose_equity_accounts(ledger,facts.evaluation_id,date(2026,10,26),date(2026,10,30),symbol=request.candidate.instrument.symbol)
        assert result.status.value=='COMPUTED'
        assert all(abs(row.residual)<1e-7 for pnl in result.pnl_breakdown for row in pnl.daily)


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('frequency', [BarFrequency.DAILY, BarFrequency.M30])
@pytest.mark.parametrize('computation', [StrategyComputation.BATCH_HISTORY, StrategyComputation.STATEFUL_STEP])
def test_stage_one_two_public_computation_clock_and_scale_in_out(tmp_path, market, frequency, computation):
    context, request = setup_account(tmp_path, market, frequency, computation)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        assert outcome.result.payload['schema'] == 'equity-research/v4'
        facts, = build_assessment_evidence(prepared, outcome.result, execution=execution)
        assert facts.equity.market == market.value
        assert facts.equity.currency == request.candidate.instrument.currency
        reference = publish_evidence(context, EvaluationEvidenceWrite(request.experiment,
            'parity', prepared, outcome.result), execution=execution)
        assert reference.schema_version == 4
        from czsc_trader.research_tools.evaluation import EvaluationIdentity
        from strategy_manager import CandidateKey
        raw_identity = dict(outcome.result.payload['evaluation_identity'])
        raw_identity['candidate'] = CandidateKey(**raw_identity['candidate'])
        identity = EvaluationIdentity(**raw_identity)
        diagnosis = diagnose_accounts(context.repository, AccountDiagnosisRequest(
            AccountRunRef(reference, identity), None,
            EvaluationWindow('all', date(2026,10,26) if frequency is BarFrequency.M30 else date(2026,10,27), date(2026,10,30))),
            execution=execution)
        assert diagnosis.status.value == 'COMPUTED', diagnosis.issues
        assert all(abs(day.residual) < 1e-7 for pnl in diagnosis.pnl_breakdown for day in pnl.daily)
    record = register_candidate(context.repository, CandidateRegistrationRequest(request.candidate,
        request.experiment, (reference,), ()))
    assert load_candidate(context.repository, request.candidate.key).content_identity.content_sha256 == record.content_sha256


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('frequency', [BarFrequency.DAILY, BarFrequency.M30])
def test_stage_three_raw_actions_and_independent_multi_fill_diagnosis(tmp_path, market, frequency):
    context, request = setup_account(tmp_path, market, frequency, events=True)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        facts, = build_assessment_evidence(prepared, outcome.result, execution=execution)
        ledger = json.loads(facts.equity.benchmark_ledger)
        assert ledger['account_contract'] == 4
        assert {row['kind'] for row in ledger['actions']} >= {'SPLIT', 'CASH_DIVIDEND', 'DIVIDEND_PAYMENT'}
        from strategy_evaluator.equity import audit_equity_account
        # Independent fact audit must reject an altered, otherwise well-formed ledger.
        damaged = dict(ledger, account_points=[dict(row) for row in ledger['account_points']])
        damaged['account_points'][-1]['cash'] += 1
        with pytest.raises(ValueError):
            audit_equity_account(**damaged, decision_contract='FORMAL_V4')
