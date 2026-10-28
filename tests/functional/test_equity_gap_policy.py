"""Explicit missing-market observations through prepare, execution and evidence."""
import json

import pandas as pd
import pytest
from dataflows import (EquityProduct, ProviderConfig, TimeInterval, UsEquityBarPolicy,
                       futu_equity_bindings)
from czsc_trader.application.research_governance_service import create_research_context
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite
from test_equity_research import setup_equity
from test_equity_closure import setup_formal_equity


def gap_context(tmp_path, *, formal=True, missing=(2, 3, 25), zero=(4,), blocked=(7,), split=False):
    context, request, products, _ = (setup_formal_equity if formal else setup_equity)(tmp_path)
    bars = products[EquityProduct.BARS].copy()
    if split:
        bars.loc[13:, ['Open', 'High', 'Low', 'Close']] /= 2
    for index in zero:
        bars.loc[index, ['Open', 'High', 'Low', 'Close']] = 20.
        bars.loc[index, ['Volume', 'Amount']] = 0.
    policy = UsEquityBarPolicy(1, .01, tuple(TimeInterval(
        bars.BarStart.iloc[i] + pd.Timedelta(minutes=5), bars.BarStart.iloc[i] + pd.Timedelta(minutes=10))
        for i in blocked))

    class Quotes:
        def request_trading_days(self, **kwargs):
            return 0, [{'time': '2026-10-01', 'trade_date_type': 'WHOLE'},
                       {'time': '2026-10-02', 'trade_date_type': 'WHOLE'}]

        def get_rehab(self, code):
            return 0, (pd.DataFrame([{'ex_div_date': '2026-10-02', 'split_ratio': 2., 'per_cash_div': 0.}])
                       if split else pd.DataFrame())

        def request_history_kline(self, code, **kwargs):
            raw = bars.drop(index=list(missing)).rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close',
                'Volume': 'volume', 'Amount': 'turnover'}).copy()
            raw['code'] = code
            raw['time_key'] = raw.Date.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d %H:%M:%S')
            return 0, raw, None

    context = create_research_context(context.repository, context.batch,
        providers=ProviderConfig(bindings={}, equity_bindings=futu_equity_bindings(
            source=request.sources.bars, quote_context=Quotes(), research_policy=policy)),
        execution_spec=context.execution_spec)
    return context, request, bars


@pytest.mark.parametrize('formal', [False, True])
def test_gap_account_preserves_causality_stale_marks_and_publication(tmp_path, formal):
    context, request, bars = gap_context(tmp_path, formal=formal)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    run = result.payload['runs']['candidate']
    points, decisions = run['account_points'], run['decisions']
    assert len(points) == 25
    # A valid signal before the gap still creates a real attempted order.
    assert decisions[1]['side'] == 'SELL'
    assert next(o for o in run['orders'] if o['decision_id'] == decisions[1]['decision_id'])['reason'] == 'MISSING_BAR'
    assert [d['signal_status'] for d in decisions[2:5]] == ['SUPPRESSED_UNOBSERVED_BAR'] * 3
    assert all(d['side'] == 'WAIT' and d['quantity'] == 0 for d in decisions[2:5])
    assert decisions[5]['side'] == 'SELL'  # Fresh observation resumes strategy evaluation.
    assert next(o for o in run['orders'] if o['decision_id'] == decisions[6]['decision_id'])['reason'] == 'KNOWN_INTERRUPTION'
    assert [p['valuation_stale'] for p in points[:6]] == [False, True, True, True, False, False]
    assert all(p['close'] == 10 for p in points[1:4])  # Zero-volume vendor price 20 is not a mark.
    assert all(pd.Timestamp(p['valuation_price_at']) == bars.Date.iloc[1] for p in points[1:4])
    assert points[-1]['valuation_stale'] is True
    blocked_ends = {bars.Date.iloc[i] for i in (2, 3, 4, 7, 25)}
    assert not any(pd.Timestamp(f['interval_end']) in blocked_ends for f in run['fills'])
    evidence = publish_evidence(context, EvaluationEvidenceWrite(request.experiment, 'gap-account', prepared, result))
    assert evidence.resolve(context.repository.root).read_bytes() == result.content
    quality = run['data_quality']
    assert quality['evaluation_window']['missing_bars'] == 3
    assert quality['evaluation_window']['zero_volume_bars'] == 1
    assert quality['evaluation_window']['known_blocked_bars'] == 1
    assert quality['evaluation_window']['affected_sessions'] == ['2026-10-01', '2026-10-02']
    assert quality['stale_valuations'] == 4 and quality['suppressed_signals'] == 3
    assert {'MISSING_BAR', 'KNOWN_INTERRUPTION'} <= {o['reason'] for o in quality['affected_orders']}


def test_current_gap_cannot_rewrite_earlier_plan_and_empty_warmup_is_rejected(tmp_path):
    original, request, _ = gap_context(tmp_path / 'complete', missing=(), zero=(), blocked=())
    complete = original.evaluation.evaluate(request).payload['runs']['candidate']
    changed, request, _ = gap_context(tmp_path / 'gap', missing=(2,), zero=(), blocked=())
    gap = changed.evaluation.evaluate(request).payload['runs']['candidate']
    # IDs carry candidate identity from separate fixture roots; compare actual plan facts.
    fields = ('observed_through', 'decision_at', 'execution_start', 'execution_end',
              'target', 'quantity', 'side', 'limit_price', 'reference_price', 'signal_status')
    assert [{k: d[k] for k in fields} for d in complete['decisions'][:2]] == [
        {k: d[k] for k in fields} for d in gap['decisions'][:2]]
    context, request, _ = gap_context(tmp_path / 'leading', missing=(0,), zero=(), blocked=())
    with pytest.raises(ValueError, match='warmup'):
        context.evaluation.evaluate(request)


@pytest.mark.parametrize('tamper', ['stale', 'mark', 'quality'])
def test_gap_evidence_rejects_fabricated_marks_and_diagnostics(tmp_path, tamper):
    from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
    context, request, _ = gap_context(tmp_path)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    payload = result.payload
    run = payload['runs']['candidate']
    if tamper == 'stale':
        run['account_points'][1]['valuation_stale'] = False
    elif tamper == 'mark':
        run['account_points'][1]['valuation_price_at'] = run['account_points'][1]['time']
    else:
        run['data_quality'] = {}
    changed = EquityEvaluationResult(result.request_hash, json.dumps(payload).encode())
    with pytest.raises(ValueError):
        publish_evidence(context, EvaluationEvidenceWrite(request.experiment, 'bad-gap', prepared, changed))


def test_held_position_across_split_and_consecutive_gaps_has_no_phantom_gain(tmp_path):
    context, request, bars = gap_context(tmp_path, missing=(13, 14), zero=(), blocked=(), split=True)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    run = result.payload['runs']['buy_hold']
    before, first, second, restored = run['account_points'][11:15]
    assert before['quantity'] == 98 and first['quantity'] == second['quantity'] == 196
    assert first['close'] == second['close'] == 5 and before['close'] == 10
    assert first['equity'] == second['equity'] == restored['equity'] == before['equity']
    assert first['valuation_stale'] and second['valuation_stale'] and not restored['valuation_stale']
    assert pd.Timestamp(first['valuation_price_at']) == bars.Date.iloc[12]
    assert run['decisions'][13]['signal_status'] == run['decisions'][14]['signal_status'] == 'SUPPRESSED_UNOBSERVED_BAR'
    assert run['decisions'][15]['signal_status'] == 'EVALUATED'
    publish_evidence(context, EvaluationEvidenceWrite(request.experiment, 'split-gaps', prepared, result))


def test_direct_planning_rejects_latest_gap_and_filters_old_gaps(tmp_path):
    from strategy_runtime import EquityPortfolio
    context, request, _ = gap_context(tmp_path, missing=(2,), zero=(), blocked=())
    prepared = context.evaluation.prepare(request)
    query = next(q for q in prepared.requests(context.execution_spec) if q.parameters.query.product is EquityProduct.BARS)
    bars = context.data.fetch(query, prepared=prepared.prepared).dataframe
    instance = context.runtime.create(request.candidate)
    with pytest.raises(ValueError, match='latest equity observation is unavailable'):
        instance.plan(bars.iloc[:3], TimeInterval(bars.BarStart.iloc[3], bars.Date.iloc[3]),
                      EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    plan = instance.plan(bars.iloc[:4], TimeInterval(bars.BarStart.iloc[4], bars.Date.iloc[4]),
                         EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    assert plan.side == 'BUY' and plan.reference_price == 10.


def test_first_execution_gap_flat_benchmark_passes_assessment_and_freeze(tmp_path):
    from czsc_trader.application import register_candidate, CandidateRegistrationRequest
    from czsc_trader.research_tools.assessment import build_assessment_evidence
    from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
    from test_equity_inspection_roundtrip import inspect_freeze

    context, request, _ = gap_context(tmp_path, missing=(1,), zero=(), blocked=())
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    run = result.payload['runs']['buy_hold']
    assert run['orders'][0]['reason'] == 'MISSING_BAR'
    assert run['account_points'][0]['quantity'] == 0
    suppressed = run['decisions'][1]
    assert suppressed['signal_status'] == 'SUPPRESSED_UNOBSERVED_BAR'
    assert suppressed['target'] == 0 and suppressed['side'] == 'WAIT'
    assert suppressed['explanation'] is None
    assert build_assessment_evidence(prepared, result)
    changed = result.payload
    changed['runs']['buy_hold']['data_quality'] = {}
    with pytest.raises(ValueError, match='archived data quality'):
        build_equity_assessment_payload(changed)
    evidence = publish_evidence(context, EvaluationEvidenceWrite(
        request.experiment, 'first-execution-gap', prepared, result))
    register_candidate(context.repository, CandidateRegistrationRequest(
        request.candidate, request.experiment, (evidence,), ()))
    inspect_freeze(context, prepared, evidence)
