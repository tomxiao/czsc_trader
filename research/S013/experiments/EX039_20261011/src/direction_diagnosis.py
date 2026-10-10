"""Declared native bear-entry direction diagnosis; zero new account evaluations."""
from collections.abc import Mapping
from dataclasses import asdict
import ast
import importlib.util
import math

import numpy as np
import pandas as pd
from strategy_runtime import CandidateContentIdentity, canonical_sha256
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import (
    EvaluationIdentity, serialize_evaluation_evidence, validate_evaluation_evidence,
)
from common import ROOT, SRC, PROTOCOLS, SOURCE_CALLS, context, read, write, cache_read, file_hash


ORACLE_SOURCE = ROOT / 'research/S013/experiments/EX036_20261011/src/confirmation_diagnosis_v2.py'
STATE_SOURCE = ROOT / 'research/S013/experiments/EX033_20261011/src/diagnose.py'
ACCOUNT_SOURCE = ROOT / 'research/S013/experiments/EX035_20261011/src/account_reference.py'
OUTPUT = ROOT / '.tmp/ex039-diagnosis/direction.json'
LIMITS = (
    'Existing repeatedly seen S013 development data only. The original center and32 joint-parameter '
    'neighbors are dependent observations of the same market path, not33 independent samples. '
    'The MEAN and BODY centers are two additional existing strategies, reported separately. '
    'Direction predicates describe original native signal opportunities and entries only. '
    'No modified holdings, orders, fills, cash, returns or trade-profit deletion sums. '
    'All original signal days and signal-date years are retained, including any2019 signal for '
    'a2020 execution; economic years remain execution-date years. No successful-year selection, '
    'new economic gate, causal effect, profit forecast, direction threshold search or independent validation.'
)
FIELD_DOCS = {
    'signal_date': 'Original native decision T; each original signal date included exactly once per account.',
    'valid_session': 'Native T+1 execution session; distinct from the grouping signal date.',
    'holding_before/route_before/age_before': 'Independently verified original predecision state; flat route=null and age=0.',
    'active_route': 'Held route before decision, or raw route when flat, as used by original predicates.',
    'eligible': 'Original route range+ACF+momentum eligibility, before original score and BODY direction gates.',
    'opportunity': 'Original flat-before and eligible; unchanged by a BODY direction refusal.',
    'score_pass': 'Original confirmation predicate, including its original scope/context semantics.',
    'entry': 'Native signal_reason=entry; an original signal entry, not a new actual-fill entry.',
    'bear_acf_raw': 'Original causal ACF20 covariance estimate from bound HFQ Close returns.',
    'bear_acf_baseline/bear_acf_centered': 'MEAN/BODY strict past-L mean and current-minus-baseline; null for original raw-ACF strategies.',
    'entry_acf_value/entry_acf_pass': 'Actual original predecision route ACF value/predicate; centered only on extra centers bear route.',
    'signal_close/signal_open/previous_signal_close': 'HFQ daily T Close/Open and strict previous actual daily session Close in same price unit.',
    'close_delta_hfq/body_delta_hfq': 'T Close minus preceding Close / T Open; no future price or actual-fill PnL.',
    'close_up/body_up': 'Fixed strict >0 direction predicates; equality and negative direction separately counted.',
    'body_gate_applies/body_gate_pass': 'EX029 BODY only: raw bear-to-bull boundary scope and direction predicate; other models False/True.',
    'target/signal_reason': 'Unmodified native binary target and independently verified reason.',
}


def verified_json(reference):
    ref = EvidenceRef.from_dict(reference)
    assert ref.experiment.strategy_id == 'S013'
    path = ref.resolve(ROOT).resolve()
    assert path.is_relative_to((ROOT / 'research/S013').resolve())
    assert file_hash(path) == ref.sha256
    return read(path)


def declared_method():
    path = PROTOCOLS / 'method_reference.json'
    assert path.is_file(), 'Declare EX039 method before reading any retained accounts'
    reference = read(path)
    ref = EvidenceRef.from_dict(reference)
    assert ref.experiment.experiment_id == SRC.parent.name == 'EX039_20261011'
    method = verified_json(reference)
    assert method['new_account_evaluations'] == 0
    assert set(method['inputs']) == {'original33', 'mean_center', 'body_center'}
    assert set(method['source_files']) == {'direction_diagnosis.py', 'focused_checks.py', 'common.py'}
    for relative, digest in method['source_files'].items():
        target = (SRC / relative).resolve()
        assert target.is_relative_to(SRC.resolve()) and file_hash(target) == digest
    for dependency in (ORACLE_SOURCE, STATE_SOURCE, ACCOUNT_SOURCE):
        assert method['external_source_files'][dependency.relative_to(ROOT).as_posix()] == file_hash(dependency)
    for relative, digest in method['external_source_files'].items():
        target = (ROOT / relative).resolve()
        assert target.is_relative_to((ROOT / 'research/S013').resolve()) and file_hash(target) == digest
    return reference, method


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


def direction_statistics(values):
    """Retain every year, both routes and both sets, including empty groups."""
    years = sorted(set(values.index.year))
    rows = []
    for year in ['ALL', *years]:
        year_mask = np.ones(len(values), bool) if year == 'ALL' else values.index.year == year
        for route in ('bull', 'bear'):
            for selected in ('opportunity', 'entry'):
                mask = year_mask & values.raw_route.eq(route).to_numpy() & values[selected].to_numpy(dtype=bool)
                count = int(mask.sum())
                directions = {}
                for prefix in ('close', 'body'):
                    directions[prefix] = {name: int((mask & values[prefix + '_' + name].to_numpy(dtype=bool)).sum())
                                          for name in ('up', 'equal', 'down')}
                    assert sum(directions[prefix].values()) == count
                cross = {a + '_' + b: int((mask & values['close_' + a].to_numpy(dtype=bool) &
                                          values['body_' + b].to_numpy(dtype=bool)).sum())
                         for a in ('up', 'equal', 'down') for b in ('up', 'equal', 'down')}
                assert sum(cross.values()) == count
                rows.append({'year': str(year), 'route': route, 'set': selected, 'count': count,
                             'score_pass_count': int((mask & values.score_pass.to_numpy(dtype=bool)).sum()),
                             'close_direction': directions['close'], 'body_direction': directions['body'],
                             'joint_direction': cross})
    for selected in ('opportunity', 'entry'):
        expected = int(values[selected].sum())
        assert sum(row['count'] for row in rows if row['year'] == 'ALL' and row['set'] == selected) == expected
        assert sum(row['count'] for row in rows if row['year'] != 'ALL' and row['set'] == selected) == expected
    return rows


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


def main():
    reference, method = declared_method()
    assert not OUTPUT.exists(), 'Retain prior output; no silent retry/overwrite'
    assert not SOURCE_CALLS
    public_identity_audit, original_oracle, state_trace, verify_account = load_original_oracle()
    refs, audits, accounts, original_values = {}, {}, {}, []
    ctx = context(1)
    try:
        prior = verified_json(method['inputs']['original33'])
        expected_refs = prior['input_accounts']
        matrix = read(ROOT / 'research/S013/assets/runs/EX015_20261011/parameter_matrix.json')
        points = sorted((row for row in matrix['rows'] if row['center'] == 'B0-TIME'), key=lambda row: row['point_index'])
        assert len(points) == 32 and [row['point_index'] for row in points] == list(range(32))
        assert set(expected_refs) == {'center', *(row['label'] for row in points)}
        transport = next(row for row in cache_read(ROOT / '.tmp/s013-mechanism-EX015/parameters/prepared.pkl.gz') if row['label'] == 'B0-TIME')
        parameter_plan = transport['plan']
        benchmark = transport['result'].runs[0].buyhold.execution
        center_identity = None

        def authenticate(label, bound, result, account_reference):
            formal = verified_json(account_reference)
            validate_evaluation_evidence(formal)
            assert formal == serialize_evaluation_evidence(bound, result)
            identity = public_identity_audit(ctx, bound, result, formal)
            audit = verify_account(bound, result)
            assert audit['known_low_error_potential_orders'] == 0
            assert len(result.runs) == 1 and not SOURCE_CALLS
            for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
                pd.testing.assert_frame_equal(getattr(benchmark, name), getattr(result.runs[0].buyhold.execution, name), check_exact=True)
            refs[label] = account_reference
            audits[label] = {'public_identity': identity, 'full_native_account': audit,
                             'serialized_account': 'EXACT_EQUAL', 'benchmark_ledgers': 'EXACT_EQUAL'}
            return identity

        def save(label, bound, result, values, population, point=None):
            expected_dates = pd.DatetimeIndex(pd.to_datetime(result.runs[0].execution.decisions.signal_date)).normalize()
            validate_days(values, expected_dates)
            assert len(values) == 1636
            records = [{'signal_date': date, **record} for date, record in
                       zip(values.index, values.to_dict('records'), strict=True)]
            accounts[label] = {'candidate_id': bound.strategy.candidate_id,
                               'content_sha256': result.runs[0].identity.content_sha256,
                               'population': population, 'point_index': point, 'native_signal_days': len(values),
                               'opportunities': int(values.opportunity.sum()), 'entries': int(values.entry.sum()),
                               'statistics': direction_statistics(values), 'all_native_days': records}

        for item in [None, *points]:
            if item is None:
                label, bound, result = 'center', transport['center'], transport['result']
            else:
                label = item['label']
                bound, result = cache_read(ROOT / '.tmp/s013-mechanism-EX015/parameters' / (label + '.pkl.gz'))
                assert expected_refs[label] == item['reference']
            identity = authenticate(label, bound, result, expected_refs[label])
            if item is None:
                assert bound.strategy.candidate_id == 'C2132'
                assert parameter_plan.design.center.content_sha256 == identity['content_sha256']
                center_identity = identity
            else:
                assert identity['source_sha256'] == center_identity['source_sha256']
                assert identity['dependency_sha256'] == center_identity['dependency_sha256']
                assert bound.strategy.candidate_id == item['candidate_id'] and identity['content_sha256'] == item['content_sha256']
                assert result.request_hash == item['request_hash'] and result.result_hash == item['result_hash']
                assert bound.lineage.parameter_binding.point == parameter_plan.design.bind_point(item['point_index'])
                plan_ref = bound.lineage.parameter_binding.plan
                assert plan_ref.experiment.experiment_id == 'EX015_20261011'
                assert verified_json(plan_ref.to_dict()) == parameter_plan.to_dict()
                derivation = bound.lineage.derivation
                assert derivation.kind.value == 'PARAMETERS'
                assert derivation.parent.candidate_id == 'C2132' and derivation.parent_content_sha256 == center_identity['content_sha256']
                assert derivation.child.candidate_id == item['candidate_id'] and derivation.child_content_sha256 == item['content_sha256']
            frame = result.runs[0].execution.decisions
            values, before, _ = original_oracle(ctx, bound, frame, bound.strategy.payload['parameters'], state_trace)
            values = enrich_original(ctx, bound, frame, values, before)
            original_values.append(values)
            save(label, bound, result, values, 'original33_dependent', None if item is None else item['point_index'])
        assert len(original_values) == 33
        for label, experiment, candidate, is_body, key in (
                ('MEAN', 'EX028_20261011', 'C8701', False, 'mean_center'),
                ('BODY', 'EX029_20261011', 'C8481', True, 'body_center')):
            account_reference = method['inputs'][key]
            assert account_reference == read(ROOT / f'research/S013/assets/runs/{experiment}/account_references.json')['N1']
            config = next(row for row in read(ROOT / f'research/S013/experiments/{experiment}/protocols/plan.json')['configurations'] if row['label'] == 'N1')
            bound, result = cache_read(ROOT / '.tmp' / ('s013-mechanism-' + experiment[:5]) / 'N1.pkl.gz')
            assert bound.strategy.candidate_id == candidate == config['candidate_id']
            assert json_standard(dict(bound.strategy.payload)) == config['payload']
            identity = authenticate(label, bound, result, account_reference)
            assert identity['content_sha256'] == config['content_sha256']
            values = reconstruct_extra(ctx, bound, result.runs[0].execution.decisions, bound.strategy.payload['parameters'], is_body)
            save(label, bound, result, values, 'additional_existing_center')
        assert len(refs) == len(accounts) == len(audits) == 35
        assert len({value['public_identity']['request_hash'] for value in audits.values()}) == 35
        assert not SOURCE_CALLS
        output = {'status': 'PASS', 'new_account_evaluations': 0, 'input_accounts': refs,
                  'method_reference': reference, 'accounts': accounts, 'audits': audits, 'fullfielddocs': FIELD_DOCS,
                  'summary': {'unique_native_accounts': 35, 'original_dependent_accounts': 33,
                              'original_parameter_points': 32, 'additional_existing_centers': 2,
                              'native_signal_rows': 35 * 1636, 'center_statistics': accounts['center']['statistics'],
                              'pooled_original33_statistics': direction_statistics(pd.concat(original_values)),
                              'additional_center_statistics': {key: accounts[key]['statistics'] for key in ('MEAN', 'BODY')},
                              'pooling_warning': 'Original33 are dependent same-market observations, not independent samples.',
                              'provider_calls': list(SOURCE_CALLS), 'cash_replays': 0}, 'limits': LIMITS}
        write(OUTPUT, json_standard(output))
        print({'direction_diagnosis': 'PASS', 'native_accounts': 35, 'new_account_evaluations': 0}, flush=True)
    except Exception as error:
        assert not OUTPUT.exists()
        write(OUTPUT, json_standard({'status': 'FAILED', 'new_account_evaluations': 0,
              'input_accounts': refs, 'audits': audits, 'method_reference': reference,
              'summary': {'authenticated_accounts': len(refs), 'provider_calls': list(SOURCE_CALLS)},
              'limits': LIMITS, 'error': {'type': type(error).__name__, 'message': str(error)},
              'policy': 'Retain failure; no replacement, provider fallback, partial PASS or automatic retry.'}))
        raise


if __name__ == '__main__':
    main()
