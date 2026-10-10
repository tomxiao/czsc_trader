"""Correct optional cycle-id serialization only; declared economics unchanged.

Only main reads retained accounts, after verifying the published method and all
declared source hashes. Signal anchors and TR are HFQ signal-model quantities;
executed exposure and equity remain the separate native fill/account path.
"""
# ruff: noqa: E402
import os

for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parents[1] / 'EX035_20261011' / 'src'
sys.path.insert(0, str(PRIOR))
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd
from strategy_runtime import implementation_sha256
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, SOURCE_CALLS, context, read, write, cache_read, file_hash
from account_reference import verify_account
from analysis_reference import annual
from ledger_reference import plain
from run_parameters import resolve_center


YEARS = tuple(range(2020, 2027))
EXITS = frozenset(('loss', 'trailing', 'range', 'time', 'regime'))
OUTPUT = ROOT / '.tmp/ex036-diagnosis/drawdown_v2.json'


def verified_json(reference):
    assert reference.experiment.strategy_id == 'S013'
    path = reference.resolve(ROOT)
    assert path.resolve().is_relative_to((ROOT / 'research/S013').resolve())
    assert file_hash(path) == reference.sha256
    return read(path)


def validate_method_sources(document):
    for relative, digest in document['source_files'].items():
        path = (SRC / relative).resolve()
        assert path.is_relative_to(SRC.resolve())
        assert file_hash(path) == digest
    for relative, digest in document['external_source_files'].items():
        path = (ROOT / relative).resolve()
        assert path.is_relative_to((ROOT / 'research/S013').resolve())
        assert file_hash(path) == digest


def declared_method():
    assert SRC.resolve() == HERE and EXPERIMENT.experiment_id == 'EX036_20261011'
    reference = EvidenceRef.from_dict(read(PROTOCOLS / 'drawdown_v2_method_reference.json'))
    assert reference.experiment.experiment_id == EXPERIMENT.experiment_id
    document = verified_json(reference)
    assert document['new_account_evaluations'] == 0
    assert document['source_files']['drawdown_diagnosis_v2.py'] == file_hash(Path(__file__))
    failed_ref = EvidenceRef.from_dict(document['failed_method_reference'])
    assert failed_ref.to_dict() == read(PROTOCOLS / 'method_references.json')['drawdown']
    assert failed_ref.experiment.experiment_id == EXPERIMENT.experiment_id
    original = verified_json(failed_ref)
    failed_source = SRC / 'drawdown_diagnosis.py'
    assert document['failed_source_sha256'] == original['source_files']['drawdown_diagnosis.py']
    assert document['failed_source_sha256'] == file_hash(failed_source)
    assert document['inputs'] == original['inputs']
    assert document['source_files']['common.py'] == original['source_files']['common.py']
    assert document['external_source_files'] == original['external_source_files']
    validate_method_sources(original)
    validate_method_sources(document)
    return reference, original


def require_finite_output(value, path=()):
    """Reject every nonfinite number; never normalize or erase missing economics."""
    if isinstance(value, dict):
        for key, nested in value.items():
            require_finite_output(nested, path + (str(key),))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            require_finite_output(nested, path + (str(index),))
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite output numeric at ' + '/'.join(path))


def authenticate(ctx, bound, result, config, reference):
    formal = verified_json(reference)
    validate_evaluation_evidence(formal)
    assert formal == serialize_evaluation_evidence(bound, result)
    assert len(result.runs) == 1 and bound.strategy.candidate_id == config['candidate_id']
    source = Path(bound.strategy.source_root).resolve()
    assert source.is_relative_to((ROOT / 'research/S013').resolve())
    runtime = bound.strategy.payload['runtime']
    digest = implementation_sha256(runtime['source_files'], source_root=source)
    assert digest == runtime['source_sha256'] == config['payload']['runtime']['source_sha256']
    identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
    assert identity.content_sha256 == config['content_sha256'] == result.runs[0].identity.content_sha256
    assert identity.source_sha256 == digest
    audit = verify_account(bound, result)
    assert audit['known_low_error_potential_orders'] == 0
    return audit, {'reference': reference.to_dict(), 'request_hash': result.request_hash,
        'result_hash': result.result_hash, 'content_sha256': identity.content_sha256,
        'source_sha256': digest, 'source_files': {name: file_hash(source / name) for name in runtime['source_files']},
        'complete_formal_serialization': 'EXACT_EQUAL', 'execution_data_identity': bound.execution_data.fingerprint}


def signal_state(ctx, bound, run):
    frame = run.execution.decisions.copy().reset_index(drop=True)
    assert frame.decision_id.is_unique and frame.valid_session.is_unique
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
    assert dates.is_unique and dates.is_monotonic_increasing
    assert len(bound.input_bindings) == 1
    binding = next(iter(bound.input_bindings.values()))
    fetched = ctx.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared)
    assert fetched.ready and not SOURCE_CALLS
    bars = fetched.dataframe.copy()
    bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    assert bars.index.is_unique and bars.index.is_monotonic_increasing
    high, low, close = (bars[name].astype(float) for name in ('High', 'Low', 'Close'))
    assert np.isfinite(bars[['High', 'Low', 'Close']].to_numpy()).all()
    assert (close > 0).all() and (high >= low).all()
    previous = close.shift(1)
    tr = pd.Series(np.maximum.reduce([(high - low).to_numpy(), (high - previous).abs().to_numpy(),
                                      (low - previous).abs().to_numpy()]), index=bars.index)
    past20 = tr.rolling(20, min_periods=20).mean().shift(1)
    prices, ranges = close.reindex(dates), past20.reindex(dates)
    assert np.isfinite(prices).all() and np.isfinite(ranges).all() and (ranges > 0).all()
    p = bound.strategy.payload['parameters']
    momentum = (close / close.shift(p['regime_window']) - 1).reindex(dates)
    assert np.isfinite(momentum).all()
    assert np.array_equal(frame.regime, np.where(momentum >= p['regime_threshold'], 'bull', 'bear'))
    holding, route, age, anchor, streak = False, None, 0, 0., 0
    rows, held = [], []
    for i, row in enumerate(frame.itertuples()):
        before, before_route = holding, route
        reason, signal_close = row.signal_reason, float(prices.iloc[i])
        adverse = two = False
        if before:
            age += 1
            assert reason == 'hold' or reason in EXITS
            adverse = before_route == 'bear' and signal_close <= anchor
            streak = streak + 1 if adverse else 0
            two = before_route == 'bear' and age >= 2 and streak >= 2
            held.append({'signal_date': dates[i], 'valid_session': pd.Timestamp(row.valid_session).normalize(),
                'active_route': before_route, 'raw_regime': row.regime, 'holding_age': age,
                'exit_reason': reason if reason in EXITS else 'none', 'signal_close_hfq': signal_close,
                'entry_anchor_signal_close_hfq': anchor, 'true_range_past20_mean_hfq': float(ranges.iloc[i]),
                'adverse_close_displacement_hfq': max(0., anchor - signal_close),
                'adverse_close_in_past20_true_ranges': max(0., anchor - signal_close) / float(ranges.iloc[i]),
                'bear_close_at_or_below_anchor': bool(adverse), 'bear_nonpositive_close_streak': streak,
                'bear_two_consecutive_nonpositive_closes': bool(two)})
            if reason in EXITS:
                holding, route = False, None
        elif reason == 'entry':
            holding, route, age, anchor, streak = True, row.regime, 0, signal_close, 0
        else:
            assert reason in ('flat', 'confirmation_rejected')
            streak = 0
        assert row.target_position in (0., 1.) and row.target_position == float(holding)
        rows.append({'decision_id': row.decision_id, 'signal_date': dates[i],
            'valid_session': pd.Timestamp(row.valid_session).normalize(), 'raw_regime': row.regime,
            'active_route': before_route if before else route if holding else 'flat',
            'signal_active_route_before': before_route or 'flat', 'signal_active_route_after': route or 'flat',
            'signal_holding_before': before, 'signal_holding_after': holding, 'signal_holding_age': age,
            'signal_reason': reason, 'observed_exit_reason': reason if reason in EXITS else 'none',
            'entry_anchor_signal_close_hfq': anchor, 'bear_two_nonpositive_signal_closes': bool(two)})
    return pd.DataFrame(rows), held, {key: value.to_dict() for key, value in bound.input_bindings.items()}


def executed_path(run, states):
    account = run.execution.account_daily.copy().reset_index(drop=True)
    account['date'] = pd.to_datetime(account.date).dt.normalize()
    assert len(account) == 1636 and account.date.is_unique and account.date.is_monotonic_increasing
    assert account.date.iloc[0] == pd.Timestamp('2020-01-02') and account.date.iloc[-1] == pd.Timestamp('2026-09-30')
    assert np.array_equal(account.date, states.valid_session)
    fills = run.execution.fills.copy()
    fills['date'] = pd.to_datetime(fills.fill_time).dt.normalize()
    assert set(fills.side) <= {'BUY', 'SELL'} and fills.fill_id.is_unique
    fill_days = {date: rows.sort_values(['fill_time', 'fill_id']) for date, rows in fills.groupby('date')}
    lookup = states.set_index('decision_id')
    quantity, cycle, execution_route = 0, None, 'flat'
    records = []
    previous_equity = 1_000_000.
    for mark, state in zip(account.itertuples(), states.to_dict('records'), strict=True):
        old_quantity, old_cycle, old_route = quantity, cycle, execution_route
        event_cycles, event_routes = set(), set()
        fees = 0.
        for fill in fill_days.get(mark.date, pd.DataFrame()).itertuples():
            assert pd.Timestamp(fill.signal_date).normalize() == lookup.loc[fill.decision_id, 'signal_date']
            assert mark.date == lookup.loc[fill.decision_id, 'valid_session']
            fees += float(fill.fees)
            if fill.side == 'BUY':
                if quantity == 0:
                    cycle, execution_route = fill.cycle_id, lookup.loc[fill.decision_id, 'raw_regime']
                assert fill.cycle_id == cycle
                quantity += int(fill.quantity)
            else:
                assert fill.cycle_id == cycle and int(fill.quantity) <= quantity
                quantity -= int(fill.quantity)
            event_cycles.add(fill.cycle_id)
            event_routes.add(execution_route)
            if quantity == 0:
                cycle, execution_route = None, 'flat'
        assert quantity == mark.quantity and len(event_cycles) <= 1 and len(event_routes) <= 1
        actual_route = old_route if old_quantity else next(iter(event_routes), 'flat')
        exposure = ('entry_day' if old_quantity == 0 and quantity > 0 else
                    'exit_day' if old_quantity > 0 and quantity == 0 else
                    'holding_day' if old_quantity > 0 and quantity > 0 else 'flat_day')
        assert previous_equity > 0 and mark.equity > 0
        records.append({**state, 'date': mark.date, 'execution_route': actual_route,
            'actual_cycle_id': old_cycle if old_quantity else next(iter(event_cycles), None),
            'exposure': exposure, 'quantity_before': old_quantity, 'quantity_after': quantity,
            'invested_before': old_quantity > 0, 'invested_after': quantity > 0,
            'cash': float(mark.cash), 'close': float(mark.close), 'equity': float(mark.equity),
            'fees': fees, 'daily_log_return': float(np.log(mark.equity / previous_equity))})
        previous_equity = float(mark.equity)
    path = pd.DataFrame(records)
    # Only the optional native cycle identifier needs object/null semantics.
    # Rebuild from original records, where an absent cycle was explicitly None.
    # Do not clean NaN/inf values in any existing column.
    path['actual_cycle_id'] = pd.Series([record['actual_cycle_id'] for record in records], dtype=object)
    return path


def log_groups(frame, columns):
    if frame.empty:
        return []
    output = []
    for keys, values in frame.groupby(columns, dropna=False, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        output.append({**dict(zip(columns, keys, strict=True)), 'days': len(values),
            'negative_log_return_days': int(values.daily_log_return.lt(0).sum()),
            'sum_daily_log_return': float(values.daily_log_return.sum()), 'fees': float(values.fees.sum())})
    assert abs(sum(row['sum_daily_log_return'] for row in output) - frame.daily_log_return.sum()) < 1e-12
    return output


def annual_drawdowns(path, expected, audited, benchmark):
    """Earliest maximum-DD trough; latest equal preceding peak; carried equity."""
    rows = []
    carry = 1_000_000.
    previous_record = {'date': None, 'equity': carry, 'cash': carry, 'quantity_after': 0, 'close': None}
    for year in YEARS:
        segment = path[path.date.dt.year.eq(year)].reset_index(drop=True)
        assert not segment.empty
        wealth = np.r_[carry, segment.equity.to_numpy(dtype=float)]
        dd = 1 - wealth / np.maximum.accumulate(wealth)
        valley = int(np.argmax(dd))
        peak = int(np.flatnonzero(wealth[:valley + 1] == np.max(wealth[:valley + 1]))[-1])
        magnitude = float(dd[valley])
        assert magnitude == expected[str(year)]['drawdown'] == audited[str(year)]['drawdown_magnitude']
        assert carry == expected[str(year)]['opening_equity']
        interval = segment.iloc[peak:valley].copy()
        log_sum = float(interval.daily_log_return.sum())
        log_ratio = float(np.log(wealth[valley] / wealth[peak]))
        residual = abs(log_sum - log_ratio)
        assert residual < 1e-12 and abs(float(-np.expm1(log_sum)) - magnitude) < 1e-12
        def mark(index):
            record = previous_record if index == 0 else segment.iloc[index - 1].to_dict()
            return {key: record[key] for key in ('date', 'equity', 'cash', 'quantity_after', 'close')}
        rows.append({'year': year, 'opening_equity': carry, 'closing_equity': float(wealth[-1]),
            'drawdown': magnitude, 'benchmark_drawdown': benchmark[str(year)]['drawdown'],
            'annual_drawdown_gate_pass': magnitude < benchmark[str(year)]['drawdown'],
            'peak': mark(peak), 'trough': mark(valley), 'interval_days': len(interval),
            'sum_daily_log_return': log_sum, 'log_peak_to_trough_ratio': log_ratio,
            'log_telescope_abs_error': residual,
            'by_executed_route': log_groups(interval, ['execution_route']),
            'by_raw_regime': log_groups(interval, ['raw_regime']),
            'by_signal_active_route': log_groups(interval, ['active_route']),
            'by_observed_exit_reason': log_groups(interval, ['observed_exit_reason']),
            'joint_groups': log_groups(interval, ['execution_route', 'raw_regime', 'active_route', 'observed_exit_reason', 'exposure']),
            'interval_daily': interval.to_dict('records')})
        carry = float(wealth[-1])
        previous_record = segment.iloc[-1].to_dict()
    return rows


def holding_summary(records):
    if not records:
        return []
    frame = pd.DataFrame(records)
    frame['year'] = pd.to_datetime(frame.signal_date).dt.year
    output = []
    for keys, group in frame.groupby(['year', 'active_route'], sort=True):
        ratio = group.adverse_close_in_past20_true_ranges
        output.append({'year': int(keys[0]), 'active_route': keys[1], 'holding_signal_bars': len(group),
            'adverse_displacement_ratio_mean': float(ratio.mean()), 'adverse_displacement_ratio_median': float(ratio.median()),
            'adverse_displacement_ratio_max': float(ratio.max()),
            'bear_nonpositive_close_bars': int(group.bear_close_at_or_below_anchor.sum()),
            'bear_two_consecutive_nonpositive_close_bars': int(group.bear_two_consecutive_nonpositive_closes.sum())})
    return output


def main():
    method_ref, method = declared_method()  # No account bytes above this barrier.
    assert not OUTPUT.exists(), 'Existing result retained; no implicit overwrite or replay'
    ctx = context(1)
    original33 = verified_json(EvidenceRef.from_dict(method['inputs']['original33']))
    original_ref = EvidenceRef.from_dict(original33['input_accounts']['center'])
    mean_ref = EvidenceRef.from_dict(method['inputs']['mean_center'])
    assert mean_ref.to_dict() == read(ROOT / 'research/S013/assets/runs/EX028_20261011/account_references.json')['N1']
    plan35 = read(ROOT / 'research/S013/experiments/EX035_20261011/protocols/plan.json')
    original_config = next(row for row in plan35['controls'] if row['label'] == 'B0-TIME')
    plan28 = read(ROOT / 'research/S013/experiments/EX028_20261011/protocols/plan.json')
    mean_config = next(row for row in plan28['configurations'] if row['label'] == 'N1')
    assert original_config['candidate_id'] == 'C2132' and mean_config['candidate_id'] == 'C8701'
    original = resolve_center(original_config)
    centered = cache_read(ROOT / '.tmp/s013-mechanism-EX028/N1.pkl.gz')
    for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
        pd.testing.assert_frame_equal(getattr(original[1].runs[0].buyhold.execution, field),
                                      getattr(centered[1].runs[0].buyhold.execution, field), check_exact=True)
    inputs, audits, rows = {}, {}, {}
    for label, pair, config, reference, analysis_path, analysis_label in (
            ('B0-TIME', original, original_config, original_ref, ROOT / 'research/S013/assets/runs/EX035_20261011/analysis.json', 'B0-TIME'),
            ('MEAN_LAGGED_ACF', centered, mean_config, mean_ref, ROOT / 'research/S013/assets/runs/EX028_20261011/analysis.json', 'N1')):
        bound, result = pair
        audit, authentication = authenticate(ctx, bound, result, config, reference)
        expected = read(analysis_path)['rows'][analysis_label]
        assert expected['candidate_id'] == config['candidate_id']
        benchmark = annual(result.runs[0].buyhold.account_daily)
        assert benchmark == expected['benchmark_annual']
        states, held, bindings = signal_state(ctx, bound, result.runs[0])
        path = executed_path(result.runs[0], states)
        drawdowns = annual_drawdowns(path, expected['annual'], audit['annual'], benchmark)
        inputs[label], audits[label] = reference.to_dict(), audit
        rows[label] = {'candidate_id': config['candidate_id'], 'content_sha256': config['content_sha256'],
            'authentication': authentication, 'analysis_path': analysis_path.relative_to(ROOT).as_posix(),
            'analysis_sha256': file_hash(analysis_path), 'original_four_gates': expected['gates'],
            'center_qualified': expected['qualified'], 'annual_drawdowns': drawdowns,
            'signal_holding_summaries': holding_summary(held), 'all_signal_holding_bars': held,
            'all_executed_days': path.to_dict('records'), 'input_bindings': bindings}
    assert not rows['MEAN_LAGGED_ACF']['center_qualified'] and not SOURCE_CALLS
    output = {'status': 'PASS', 'new_account_evaluations': 0, 'input_accounts': inputs,
        'account_audits': audits, 'rows': rows, 'method_reference': method_ref.to_dict(),
        'summary': {'native_accounts': 2, 'natural_year_intervals': 14, 'all_account_days_per_center': 1636,
            'benchmark_ledgers': 'EXACT_EQUAL all five', 'provider_calls': SOURCE_CALLS,
            'dd_boundary': 'Annual opening equity is carried from the continuous preceding account; no annual reset.',
            'tie_rule': 'Earliest maximum-DD trough; latest equal equity peak on or before that trough.',
            'precision': 'Annual DD exactly equals existing annual analysis and native cash audit; grouped/log telescope tolerance 1e-12.',
            'adverse_scope': 'Every subsequent signal-model held bar including signal exits; entry age0 excluded. HFQ signal entry anchor and absolute HFQ TrueRange. TRpast20=TR.rolling(20,min_periods=20).mean().shift(1).',
            'execution_scope': 'Native fills reconstruct actual invested state/route; each account T joins its valid T-1 signal state. Signal exit can differ from actual fill exposure.'},
        'limits': ['All seven years and all holding-signal bars retained; no profit/date/threshold exceptions.',
            'Route/log groups allocate one observed native path; they are not standalone drawdowns, causal effects, or profits obtainable by removing a group.',
            'Signal entry Close is a model anchor, not actual fill price, break-even net of fees, or a proposed stop.',
            'Two nonpositive bear closes are descriptive fixed state flags, not a new risk rule or account replay.',
            'Model route/age/reset may differ from executed inventory; both are retained rather than equated.',
            'Development pool repeatedly seen; joint parameter and path diagnostics do not isolate one parameter or establish future robustness.',
            'C8701 remains an unqualified diagnostic center; no registration, promotion, new economic veto, phase advancement, or deployment.']}
    output['correction'] = {'failed_method_reference': read(PROTOCOLS / 'method_references.json')['drawdown'],
        'failed_source_sha256': file_hash(SRC / 'drawdown_diagnosis.py'),
        'scope': 'Only optional actual_cycle_id explicitly absent in native record is JSON null, preserved with object dtype; economics/routes/math unchanged.',
        'nonfinite_policy': 'Reject all nonfinite numeric values; no allow_nan or generic missing-value cleanup.'}
    serializable = plain(output)
    require_finite_output(serializable)
    write(OUTPUT, serializable)
    print({'drawdown_diagnosis': 'PASS', 'new_accounts': 0, 'annual_intervals': 14,
           'output': OUTPUT.relative_to(ROOT).as_posix()}, flush=True)


if __name__ == '__main__':
    main()
