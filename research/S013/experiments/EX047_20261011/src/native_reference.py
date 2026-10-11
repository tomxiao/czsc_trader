"""Exact frozen native identity, feature and full-state reference functions."""
from collections.abc import Mapping
from dataclasses import asdict
import ast
import importlib.util
import math
import numpy as np
import pandas as pd
from strategy_runtime import CandidateContentIdentity, canonical_sha256
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import EvaluationIdentity
from common import ROOT, SOURCE_CALLS, read, file_hash

ORACLE_SOURCE = ROOT / 'research/S013/experiments/EX036_20261011/src/confirmation_diagnosis_v2.py'
STATE_SOURCE = ROOT / 'research/S013/experiments/EX033_20261011/src/diagnose.py'
ACCOUNT_SOURCE = ROOT / 'research/S013/experiments/EX035_20261011/src/account_reference.py'


def verified_json(reference):
    ref = EvidenceRef.from_dict(reference)
    assert ref.experiment.strategy_id == 'S013'
    path = ref.resolve(ROOT).resolve()
    assert path.is_relative_to((ROOT / 'research/S013').resolve())
    assert file_hash(path) == ref.sha256
    return read(path)


def load_original_oracle():
    """Compile only declared frozen functions; never import an old common/main."""
    names = {'public_identity_audit', 'load_auditors', 'independently_reconstruct'}
    tree = ast.parse(ORACLE_SOURCE.read_text(encoding='utf-8-sig'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    namespace = dict(globals())
    namespace.update(Mapping=Mapping, asdict=asdict, CandidateContentIdentity=CandidateContentIdentity,
                     EvaluationIdentity=EvaluationIdentity, canonical_sha256=canonical_sha256)
    namespace['importlib'] = importlib
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ORACLE_SOURCE), 'exec'), namespace)
    state_trace, verify_account = namespace['load_auditors']()
    return namespace['public_identity_audit'], namespace['independently_reconstruct'], state_trace, verify_account


def direction_fields(close, opening, previous):
    values = np.column_stack((close, opening, previous)).astype(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Current HFQ Close/Open and strict previous Close must be finite positive')
    close_delta, body_delta = values[:, 0] - values[:, 2], values[:, 0] - values[:, 1]
    return {'signal_close': values[:, 0], 'signal_open': values[:, 1], 'previous_signal_close': values[:, 2],
            'close_delta_hfq': close_delta, 'body_delta_hfq': body_delta,
            'close_up': close_delta > 0, 'close_equal': close_delta == 0, 'close_down': close_delta < 0,
            'body_up': body_delta > 0, 'body_equal': body_delta == 0, 'body_down': body_delta < 0}


def bound_bars(ctx, bound):
    assert len(bound.input_bindings) == 1
    binding = next(iter(bound.input_bindings.values()))
    fetched = ctx.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared)
    assert fetched.ready and not SOURCE_CALLS, 'Existing prepared S013 input only'
    bars = fetched.dataframe.copy()
    bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    assert bars.index.is_unique and bars.index.is_monotonic_increasing
    return bars


def enrich_original(ctx, bound, frame, values, before):
    bars = bound_bars(ctx, bound)
    dates = values.index
    fields = direction_fields(bars.Close.reindex(dates), bars.Open.reindex(dates),
                              bars.Close.shift(1).reindex(dates))
    output = values.loc[:, ['raw_route', 'active_route', 'holding_before', 'eligible',
                            'opportunity', 'score_pass', 'entry', 'target', 'score', 'threshold']].copy()
    for name, value in fields.items():
        output[name] = value
    output['route_before'] = pd.Series([state[1] for state in before], index=dates, dtype=object)
    output['age_before'] = [state[2] for state in before]
    output['bear_acf_raw'] = values.raw_acf
    output['bear_acf_baseline'] = pd.Series([None] * len(dates), index=dates, dtype=object)
    output['bear_acf_centered'] = pd.Series([None] * len(dates), index=dates, dtype=object)
    output['entry_acf_value'] = values.raw_acf
    p = bound.strategy.payload['parameters']
    output['entry_acf_pass'] = [p[route]['acf_min'] is None or acf >= p[route]['acf_min']
                               for route, acf in zip(values.active_route, values.raw_acf, strict=True)]
    output['body_gate_applies'], output['body_gate_pass'] = False, True
    output['signal_reason'] = frame.signal_reason.to_numpy()
    output['valid_session'] = pd.to_datetime(frame.valid_session).to_numpy()
    output['confirmation_opportunity'] = output.opportunity
    return output


def reconstruct_extra(ctx, bound, frame, p, is_body):
    """Independent raw features/ranks and complete native MEAN/BODY state oracle."""
    assert p['mechanism'] == ('MEAN_ACF_NEW_BULL_BODY' if is_body else 'BEAR_ACF_CENTER_MEAN')
    assert p['context'] == {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'}
    c = p['confirmation']
    assert c['enabled'] is True and c['scope'] == 'both' and c['orientation'] == 1 and c['profile'] == 'all'
    bars = bound_bars(ctx, bound)
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
    assert len(dates) == 1636 and dates.is_unique and dates.is_monotonic_increasing
    close, amount, volume = (bars[name].astype(float) for name in ('Close', 'Amount', 'Volume'))
    for series in (close, amount, volume):
        assert np.isfinite(series.to_numpy()).all() and (series > 0).all()

    def covariance(items):
        centered = items - items.mean()
        variance = np.mean(centered ** 2)
        return np.nan if np.isclose(variance, 0) else float(np.dot(centered[1:], centered[:-1]) / 19 / variance)

    def rank(items):
        return float((np.count_nonzero(items < items[-1]) + .5 * np.count_nonzero(items == items[-1])) / len(items) - .5)

    raw_acf = close.pct_change(fill_method=None).rolling(20).apply(covariance, raw=True)
    baseline = raw_acf.shift(1).rolling(c['lookback'], min_periods=c['lookback']).mean().reindex(dates)
    centered = raw_acf.reindex(dates) - baseline
    raw = pd.DataFrame({'acf': raw_acf, 'turnover': amount / amount.rolling(20).mean(),
                        'volume': np.log(volume).diff().rolling(20).mean()}, index=bars.index)
    normalized = raw.apply(lambda series: series.rolling(c['lookback'], min_periods=c['lookback']).apply(rank, raw=True)).reindex(dates)
    score = .5 * normalized.acf + .25 * normalized.turnover + .25 * normalized.volume
    assert np.isfinite(normalized.to_numpy()).all() and np.isfinite(centered.to_numpy()).all()
    for name in normalized:
        np.testing.assert_array_equal(frame['confirmation_' + name], normalized[name])
    for name, expected in (('bear_acf_raw', raw_acf.reindex(dates)), ('bear_acf_baseline', baseline),
                           ('bear_acf_centered', centered), ('acf1', raw_acf.reindex(dates)),
                           ('confirmation_score', score), ('close', close.reindex(dates))):
        np.testing.assert_array_equal(frame[name], expected)
    positions = {route: ((close - bars.Low.rolling(p[route]['range_window']).min()) /
                        (bars.High.rolling(p[route]['range_window']).max() - bars.Low.rolling(p[route]['range_window']).min())).reindex(dates)
                 for route in ('bull', 'bear')}
    for route in positions:
        assert np.isfinite(positions[route]).all()
        np.testing.assert_array_equal(frame[route + '_range_position'], positions[route])
    momentum20 = (close / close.shift(20) - 1).reindex(dates)
    all_momentum = close / close.shift(p['regime_window']) - 1
    momentum = all_momentum.reindex(dates)
    previous_momentum = all_momentum.shift(1).reindex(dates)
    assert np.isfinite(momentum).all() and np.isfinite(previous_momentum).all()
    regimes = np.where(momentum >= p['regime_threshold'], 'bull', 'bear')
    previous_regimes = np.where(previous_momentum >= p['regime_threshold'], 'bull', 'bear')
    np.testing.assert_array_equal(frame.momentum20, momentum20)
    np.testing.assert_array_equal(frame.regime_momentum, momentum)
    np.testing.assert_array_equal(frame.regime, regimes)
    fields = direction_fields(close.reindex(dates), bars.Open.reindex(dates), close.shift(1).reindex(dates))
    gate = (regimes == 'bull') & (previous_regimes == 'bear') if is_body else np.zeros(len(dates), bool)
    if is_body:
        for name, expected in (('previous_regime', previous_regimes), ('previous_regime_momentum', previous_momentum),
                               ('entry_direction_gate_applies', gate), ('entry_direction_up', fields['body_up']),
                               ('entry_signal_close', fields['signal_close']), ('entry_signal_open', fields['signal_open']),
                               ('previous_signal_close', fields['previous_signal_close'])):
            np.testing.assert_array_equal(frame[name], expected)
    holding, active, age, anchor, peak, last = False, None, 0, 0., 0., None
    records = []
    for i, row in enumerate(frame.itertuples()):
        route = active if holding else regimes[i]
        rp = p[route]
        position = positions[route].iloc[i]
        entry_acf = centered.iloc[i] if route == 'bear' else raw_acf.reindex(dates).iloc[i]
        acf_pass = rp['acf_min'] is None or entry_acf >= rp['acf_min']
        eligible = bool(position <= rp['entry'] and acf_pass and
                        (rp['momentum_min'] is None or momentum20.iloc[i] >= rp['momentum_min']))
        opportunity, passed = bool(not holding and eligible), bool(score.iloc[i] >= c['threshold'])
        assert row.range_position == position and row.entry_acf_value == entry_acf
        assert bool(row.entry_acf_pass) == bool(acf_pass)
        assert bool(row.confirmation_opportunity) == opportunity and bool(row.confirmation_pass) == passed
        assert row.confirmation_exit_context == (last or 'initial')
        record = {'raw_route': str(regimes[i]), 'active_route': str(route), 'holding_before': holding,
                  'route_before': active, 'age_before': age if holding else 0,
                  'eligible': eligible, 'opportunity': opportunity, 'score_pass': passed,
                  'score': float(score.iloc[i]), 'threshold': c['threshold'],
                  'bear_acf_raw': float(raw_acf.reindex(dates).iloc[i]),
                  'bear_acf_baseline': float(baseline.iloc[i]), 'bear_acf_centered': float(centered.iloc[i]),
                  'entry_acf_value': float(entry_acf), 'entry_acf_pass': bool(acf_pass),
                  'body_gate_applies': bool(gate[i]), 'body_gate_pass': bool(not gate[i] or fields['body_up'][i]),
                  'valid_session': pd.Timestamp(row.valid_session)}
        reason = 'flat'
        if holding:
            age += 1
            peak = max(peak, fields['signal_close'][i])
            loss = rp['stop_loss'] is not None and fields['signal_close'][i] / anchor - 1 <= -rp['stop_loss']
            trail = rp['trailing_stop'] is not None and fields['signal_close'][i] / peak - 1 <= -rp['trailing_stop']
            reason = ('loss' if loss else 'trailing' if trail else 'range' if position >= rp['exit']
                      else 'time' if age >= rp['max_hold'] else
                      'regime' if p['exit_on_regime_change'] and regimes[i] != active else 'hold')
            if reason != 'hold':
                holding, active, last = False, None, reason
        elif eligible:
            reason = ('entry_direction_rejected' if not record['body_gate_pass'] else
                      'entry' if passed else 'confirmation_rejected')
            if passed and record['body_gate_pass']:
                holding, active, age = True, str(regimes[i]), 0
                anchor = peak = fields['signal_close'][i]
                last = None
        assert row.signal_reason == reason and row.target_position == float(holding)
        record.update(signal_reason=reason, target=float(holding), entry=reason == 'entry')
        record.update({name: values[i] for name, values in fields.items()})
        records.append(record)
    # Object dtype preserves original no-route None rather than pandas NaN.
    output = pd.DataFrame(records, index=dates)
    output['route_before'] = pd.Series([record['route_before'] for record in records], index=dates, dtype=object)
    return output


def validate_days(values, expected_dates=None):
    if not values.index.is_unique or not values.index.is_monotonic_increasing:
        raise ValueError('Each account must preserve unique ordered native dates')
    if expected_dates is not None and not values.index.equals(pd.DatetimeIndex(expected_dates).normalize()):
        raise ValueError('No native signal date may be selected or removed')
    if not set(values.raw_route) <= {'bull', 'bear'}:
        raise ValueError('Invalid raw route')
    for prefix in ('close', 'body'):
        total = sum(values[prefix + '_' + name].to_numpy(dtype=int) for name in ('up', 'equal', 'down'))
        if not np.all(total == 1):
            raise ValueError('Direction partition must be mutually exclusive and complete')
    assert np.all(~values.entry.to_numpy(dtype=bool) | values.opportunity.to_numpy(dtype=bool))
    assert np.all(~values.entry.to_numpy(dtype=bool) | values.score_pass.to_numpy(dtype=bool))


def json_standard(value):
    """Validate all numerics; preserve explicit absent metadata, never clean NaN."""
    if isinstance(value, Mapping):
        return {str(key): json_standard(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_standard(nested) for nested in value]
    if isinstance(value, np.generic):
        return json_standard(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite diagnosis numeric')
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError('Unsupported diagnosis value: ' + type(value).__name__)
