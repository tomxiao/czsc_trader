"""Independent scalar review of immutable S013 ledgers, never an evaluator."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from strategy_manager import CandidateKey, StrategyRegistry

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / '.tmp/s013-new-four-203/results.json'
INVENTORY = ROOT / 'research/S013/reviews/20261012_existing_candidates/review.json'
CONTRACT = '7c751496de5bc7cf108e28067a859666d42fd7687f37e08253778f49c7dc7099'
TOL = 1e-6


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(actual, expected, tolerance=1e-10):
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in expected.items():
            assert key in actual, key
            equal(actual[key], value, tolerance)
    elif isinstance(expected, (list, tuple)):
        assert list(actual) == list(expected), (actual, expected)
    elif isinstance(expected, bool) or expected is None or isinstance(expected, str):
        assert actual == expected and (not isinstance(expected, bool) or type(actual) is bool)
    elif isinstance(expected, int):
        assert actual == expected, (actual, expected)
    else:
        assert math.isfinite(actual) and math.isfinite(expected)
        assert abs(actual-expected) <= tolerance, (actual, expected)


def dd(values):
    peak = values[0]
    result = 0.0
    for value in values:
        assert math.isfinite(value) and value > 0
        peak = max(peak, value)
        result = max(result, 1-value/peak)
    return result


def annual(axis, equities, initial, closed):
    grouped = defaultdict(list)
    for date, equity in zip(axis, equities, strict=True):
        grouped[date[:4]].append(equity)
    before = initial
    years = {}
    for year, values in sorted(grouped.items()):
        years[year] = {
            'opening_equity': before, 'closing_equity': values[-1],
            'return': values[-1]/before-1, 'drawdown': dd([before, *values]),
            'sessions': len(values),
            'closed_cycles': sum(date.startswith(year) for date in closed.values()),
        }
        before = values[-1]
    return years


def reconcile(account, fills, initial, closed=None):
    """Rebuild each cash/mark from all realised fill flows using scalar fsum."""
    axis = [row.get('session', row.get('date', ''))[:10] for row in account]
    assert axis == sorted(set(axis)) and axis
    grouped = defaultdict(list)
    cycle_quantity = defaultdict(int)
    cycle_cash = defaultdict(list)
    cycle_last = {}
    for fill in fills:
        date = fill.get('session', fill.get('fill_time', ''))[:10]
        assert date in axis
        grouped[date].append(fill)
    flows = [initial]
    quantity = 0
    maximum = 0.0
    equities = []
    for date, row in zip(axis, account, strict=True):
        for fill in grouped[date]:
            assert fill['side'] in ('BUY', 'SELL')
            shares = fill['quantity']
            assert int(shares) == shares and shares > 0 and shares % 100 == 0
            price, fee = float(fill['price']), float(fill['fees'])
            assert math.isfinite(price) and price > 0
            assert abs(fee-shares*price*.001) <= TOL
            sign = 1 if fill['side'] == 'BUY' else -1
            flow = -sign*shares*price-fee
            flows.append(flow)
            quantity += sign*shares
            key = fill['cycle_id']
            cycle_quantity[key] += sign*shares
            cycle_cash[key].append(flow)
            cycle_last[key] = date
            assert quantity >= 0 and cycle_quantity[key] >= 0
        cash = math.fsum(flows)
        equity = math.fsum((cash, quantity*float(row['close'])))
        maximum = max(maximum, abs(cash-row['cash']), abs(equity-row['equity']))
        assert cash >= -TOL and row['quantity'] == quantity and maximum <= TOL
        equities.append(float(row['equity']))
    derived = {key: cycle_last[key] for key, value in cycle_quantity.items() if value == 0}
    if closed is not None:
        assert derived == closed
    pnl = math.fsum(math.fsum(values) for values in cycle_cash.values())
    pnl = math.fsum((pnl, quantity*float(account[-1]['close'])))
    assert abs(pnl-(equities[-1]-initial)) <= TOL
    return axis, equities, derived, maximum


def gates(facts, bh_cagr, bh_years):
    years = facts['annual']
    positive = [int(y) for y, values in bh_years.items() if values['return'] > 0]
    assert positive and set(years) == set(bh_years)
    days = sum(years[str(y)]['sessions'] for y in positive)
    trades = sum(years[str(y)]['closed_cycles'] for y in positive)
    all_days = sum(values['sessions'] for values in years.values())
    all_trades = sum(values['closed_cycles'] for values in years.values())
    flags = {
        'return': facts['net_cagr'] >= 1.5*bh_cagr if bh_cagr > 0 else facts['net_cagr'] > 0,
        'annual_drawdown': all(years[y]['drawdown'] < bh_years[y]['drawdown'] for y in years),
        'positive_buyhold_year_frequency': 15*trades >= days,
        'negative_buyhold_year_profit': all(years[y]['return'] > 0 for y in years if bh_years[y]['return'] < 0),
    }
    return {'gates': flags, 'qualified': all(flags.values()), 'positive_years': positive,
            'positive_sessions': days, 'positive_closed_cycles': trades,
            'positive_frequency60': 60*trades/days,
            'all_year_frequency60': 60*all_trades/all_days}


def verify(result_path=RESULTS):
    result = read(Path(result_path))
    historical = read(INVENTORY)['registered_inventory']
    inventory = {row['candidate_id']: row for row in historical}
    rows = {row['candidate_id']: row for row in result['rows']}
    assert len(inventory) == len(rows) == 203
    assert set(rows) == set(inventory)
    registry_paths = list((ROOT/'research/registrations/S013/candidates').glob('*.json'))
    assert {p.stem for p in registry_paths} == set(inventory)
    registry = StrategyRegistry(ROOT/'research/registrations')
    benchmark_info = result['benchmark']
    benchmark_path = ROOT/benchmark_info['source']
    assert digest(benchmark_path) == benchmark_info['source_sha256']
    benchmark_native = read(benchmark_path)
    benchmark_assessment = benchmark_native['assessment_evidence'][0]
    assert benchmark_native['schema_version'] == 6
    assert benchmark_assessment['scenario_context']['benchmark_contract_sha256'] == CONTRACT
    equal(benchmark_native['request_identity']['benchmark']['execution'], {
        'type': 'LimitBuyHold', 'premium': .01, 'lot_size': 100,
        'price_tick': .001, 'price_limit_ratio': .1, 'maximum_order_quantity': 1000000,
    })
    bh = benchmark_native['runs'][0]['buyhold']
    bh_account = bh['account_daily']['data']
    bh_axis, bh_equities, _, bh_error = reconcile(bh_account, bh['execution']['fills']['data'], 1e6)
    equal(benchmark_assessment['benchmark_equity'], bh_equities)
    bh_year_full = annual(bh_axis, bh_equities, 1e6, {})
    bh_years = {y: {'return': v['return'], 'drawdown': v['drawdown']} for y, v in bh_year_full.items()}
    bh_cagr = (bh_equities[-1]/1e6)**(252/len(bh_equities))-1
    equal(benchmark_info['benchmark_cagr'], bh_cagr)
    equal(benchmark_info['benchmark_annual'], bh_years)
    assert len(bh_axis) == 1636 and bh_axis[0] == '2020-01-02' and bh_axis[-1] == '2026-09-30'
    reference_daily = benchmark_native['runs'][0]['replay_evidence']['execution_daily']
    reference_intraday = benchmark_native['runs'][0]['replay_evidence']['execution_intraday']
    pricing = benchmark_native['request_identity']['pricing']
    premiums, schemas, gate_counts = Counter(), Counter(), Counter()
    passed, maximum_error, total_fills, total_closed = [], bh_error, 0, 0
    for cid, reported in sorted(rows.items()):
        inv = inventory[cid]
        assert reported['content_sha256'] == inv['content_sha256']
        path = ROOT/reported['source']
        assert digest(path) == reported['source_sha256'] == inv['source_sha256']
        assert reported['source'] == inv['source']
        record = registry.get_candidate(CandidateKey('S013', cid), evidence_root=ROOT/'research/S013')
        assert record.content_sha256 == reported['content_sha256']
        for origin in record.origin.evidence:
            assert digest(ROOT/'research/S013'/origin.path) == origin.sha256
        native = read(path)
        assert native['schema_version'] == reported['schema_version']
        assert len(native['assessment_evidence']) == len(native['runs']) == 1
        evidence = native['assessment_evidence'][0]
        assert evidence['candidate']['candidate_id'] == 'S013-'+cid
        assert evidence['candidate']['content_sha256'] == record.content_sha256
        equal(native['request_identity']['pricing'], pricing)
        assert native['data_identity'] == benchmark_native['data_identity']
        assert native['request_identity']['symbol'] == '510500.SH'
        assert native['request_identity']['windows'] == benchmark_native['request_identity']['windows']
        assert evidence['initial_cash'] == evidence['opening_cash'] == 1e6
        assert evidence['opening_quantity'] == 0 and evidence['scenario_context']['one_way_cost'] == .001
        replay = native['runs'][0]['replay_evidence']
        assert replay['execution_daily'] == reference_daily
        assert replay['execution_intraday'] == reference_intraday
        spec = replay['execution_spec']
        equal(spec['pricing'], pricing)
        assert spec['fee_rate'] == .001 and spec['entry_order_type'] == 'LIMIT'
        assert spec['exit_order_type'] == 'MARKET' and spec['instrument']['lot_size'] == 100
        assert spec['allocation_fraction'] == 1.0 and spec['capital_mode'] == 'AVAILABLE_CASH'
        premiums[spec['entry_limit_parameter']] += 1
        schemas[native['schema_version']] += 1
        closed = {r['cycle_id']: r['exit_session'] for r in evidence['closed_cycles']}
        assert len(closed) == len(evidence['closed_cycles'])
        axis, equities, actual_closed, error = reconcile(evidence['account'], evidence['fills'], 1e6, closed)
        assert axis == bh_axis
        assert [r['close'] for r in evidence['account']] == [r['close'] for r in bh_account]
        facts = {'net_cagr': (equities[-1]/1e6)**(252/len(axis))-1,
                 'full_drawdown': dd([1e6, *equities]), 'closed_trades': len(actual_closed),
                 'frequency60': 60*len(actual_closed)/len(axis),
                 'annual': annual(axis, equities, 1e6, actual_closed)}
        equal(reported['economics'], facts)
        grade = gates(facts, bh_cagr, bh_years)
        equal(reported['gates_v2'], grade)
        for key, value in grade['gates'].items():
            gate_counts[key] += value
        if grade['qualified']:
            passed.append(cid)
        maximum_error = max(maximum_error, error)
        total_fills += len(evidence['fills'])
        total_closed += len(actual_closed)
    return {'status': 'PASS', 'independently_verified_candidates': 203,
            'passed_candidates': passed, 'gate_counts': dict(gate_counts),
            'schema_counts': dict(schemas), 'original_execution_premium_counts': dict(premiums),
            'all_daily_and_intraday_prices_exact': True, 'all_sessions_exact': True,
            'authenticated_registry_content_and_origins': 203,
            'actual_fills_verified': total_fills, 'actual_closed_cycles_verified': total_closed,
            'maximum_cash_mark_error': maximum_error,
            'benchmark_cagr': bh_cagr, 'positive_years': [int(y) for y in bh_years if bh_years[y]['return'] > 0],
            'new_accounts': 0, 'new_experiments': 0, 'new_fits': 0,
            'scope': 'Independent fsum actual-ledger review; immutable original strategies and one authenticated current benchmark. No claim of normalised strategy premium or 32-point robustness.'}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2, allow_nan=False))
