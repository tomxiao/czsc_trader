"""Declared native confirmation diagnosis; zero new account evaluations."""
from collections import Counter
import ast
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from common import ROOT, SRC, SOURCE_CALLS, context, read, write, cache_read, file_hash
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from strategy_runtime import canonical_sha256

PROTOCOLS = SRC.parent / 'protocols'
OUTPUT = ROOT / '.tmp/ex036-diagnosis/confirmation.json'
STATE_SOURCE = ROOT / 'research/S013/experiments/EX033_20261011/src/diagnose.py'
ACCOUNT_SOURCE = ROOT / 'research/S013/experiments/EX035_20261011/src/account_reference.py'
LIMITS = (
    'All33 original native accounts/all32 joint-coordinate neighbors; repeatedly seen S013 development pool. '
    'Every native signal date and natural signal-date year included, including any preceding-year signal for '
    'the first2020 execution. Opportunity/component/weight comparisons are predicates on each original native '
    'path, not new strategies or counterfactual cash replay. Alternative weights and crossed scores do not '
    'propagate holdings, orders, fills, cash or returns. Equal predecision flat strategy state does not mean '
    'equal inherited cash. Joint parameter/normalization/raw-route/eligibility changes are not single-parameter '
    'causal effects. No new economic gate, date selection, threshold search, profit forecast or independent validation.'
)


def declared_method():
    """Fail before reading native results unless both methods exist and ours is frozen."""
    path = PROTOCOLS / 'method_references.json'
    assert path.is_file(), 'Declare both EX036 methods before reading native account results'
    references = read(path)
    assert set(references) == {'confirmation', 'drawdown'}
    methods = {}
    for name, document in references.items():
        ref = EvidenceRef.from_dict(document)
        assert ref.experiment.strategy_id == 'S013' and ref.experiment.experiment_id == SRC.parent.name
        assert file_hash(ref.resolve(ROOT)) == ref.sha256
        methods[name] = read(ref.resolve(ROOT))
    method = methods['confirmation']
    assert method['source_files']['confirmation_diagnosis.py'] == file_hash(Path(__file__).resolve())
    assert method['source_files']['common.py'] == file_hash(SRC / 'common.py')
    for relative, digest in method['source_files'].items():
        target = (SRC / relative).resolve()
        assert target.is_relative_to(SRC.resolve())
        assert file_hash(target) == digest
    external = method['external_source_files']
    for dependency in (STATE_SOURCE, ACCOUNT_SOURCE):
        assert external[dependency.relative_to(ROOT).as_posix()] == file_hash(dependency)
    for relative, digest in external.items():
        assert relative.startswith('research/S013/') and '..' not in Path(relative).parts
        assert file_hash(ROOT / relative) == digest
    return references['confirmation'], method


def load_auditors():
    """Load source-only functions without importing EX033 common or changing sys.path."""
    parsed = ast.parse(STATE_SOURCE.read_text(encoding='utf-8-sig'))
    functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == 'state_trace']
    assert len(functions) == 1
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(STATE_SOURCE), 'exec'), namespace)
    spec = importlib.util.spec_from_file_location('s013_ex036_native_account_auditor', ACCOUNT_SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return namespace['state_trace'], module.verify_account


def distribution(values):
    values = np.asarray(values, dtype=float)
    assert np.isfinite(values).all()
    if not len(values):
        return {'count': 0, 'min': None, 'tertile1': None, 'median': None,
                'tertile2': None, 'max': None, 'mean': None}
    quantiles = np.quantile(values, [1/3, .5, 2/3], method='linear')
    return {'count': len(values), 'min': float(values.min()), 'tertile1': float(quantiles[0]),
            'median': float(quantiles[1]), 'tertile2': float(quantiles[2]),
            'max': float(values.max()), 'mean': float(values.mean())}


def bool_table(first, second):
    first, second = np.asarray(first, bool), np.asarray(second, bool)
    assert len(first) == len(second)
    return {'both_pass': int((first & second).sum()), 'first_only': int((first & ~second).sum()),
            'second_only': int((~first & second).sum()), 'both_reject': int((~first & ~second).sum())}


def independently_reconstruct(ctx, bound, frame, parameters, state_trace):
    """Original OHLC/rank/score/state oracle on the authenticated bound full history."""
    p = parameters
    assert p['context'] == {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'}
    assert p['confirmation']['enabled'] is True and p['confirmation']['profile'] == 'all'
    assert p['confirmation']['scope'] == 'both' and p['confirmation']['orientation'] == 1
    assert len(bound.input_bindings) == 1
    binding = next(iter(bound.input_bindings.values()))
    fetched = ctx.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared)
    assert fetched.ready and not SOURCE_CALLS, 'Only original prepared S013 data are allowed'
    bars = fetched.dataframe.copy()
    bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    assert bars.index.is_unique and bars.index.is_monotonic_increasing
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
    assert dates.is_unique and dates.is_monotonic_increasing and len(dates) == 1636
    assert pd.Timestamp('2020-01-02') == pd.Timestamp(bound.windows[0].start)
    assert pd.Timestamp('2026-09-30') == pd.Timestamp(bound.windows[0].end)
    close = bars.Close.astype(float)
    amount, volume = bars.Amount.astype(float), bars.Volume.astype(float)
    assert np.isfinite(volume).all() and np.isfinite(amount).all() and (volume > 0).all() and (amount > 0).all()

    def acf(items):
        centered = items-items.mean()
        variance = np.mean(centered**2)
        return np.nan if np.isclose(variance, 0) else float(np.dot(centered[1:], centered[:-1])/19/variance)

    full_acf = close.pct_change(fill_method=None).rolling(20).apply(acf, raw=True)
    raw = pd.DataFrame({'acf': full_acf, 'turnover': amount/amount.rolling(20).mean(),
                        'volume': np.log(volume).diff().rolling(20).mean()}, index=bars.index)

    def rank(items):
        current = items[-1]
        return float((np.count_nonzero(items < current)+.5*np.count_nonzero(items == current))/len(items)-.5)

    lookback = p['confirmation']['lookback']
    normalized = raw.apply(lambda values: values.rolling(lookback, min_periods=lookback).apply(rank, raw=True)).reindex(dates)
    raw = raw.reindex(dates)
    assert np.isfinite(raw.to_numpy()).all() and np.isfinite(normalized.to_numpy()).all()
    for name in normalized:
        np.testing.assert_array_equal(frame['confirmation_'+name], normalized[name])
    score = .5*normalized.acf+.25*normalized.turnover+.25*normalized.volume
    np.testing.assert_array_equal(frame.confirmation_score, score)
    np.testing.assert_array_equal(frame.acf1, full_acf.reindex(dates))
    np.testing.assert_array_equal(frame.close, close.reindex(dates))
    for route in ('bull', 'bear'):
        low = bars.Low.rolling(p[route]['range_window']).min()
        high = bars.High.rolling(p[route]['range_window']).max()
        position = ((close-low)/(high-low)).reindex(dates)
        assert np.isfinite(position).all()
        np.testing.assert_array_equal(frame[route+'_range_position'], position)
    momentum20 = (close/close.shift(20)-1).reindex(dates)
    np.testing.assert_array_equal(frame.momentum20, momentum20)
    momentum = (close/close.shift(p['regime_window'])-1).reindex(dates)
    assert np.isfinite(momentum).all()
    np.testing.assert_array_equal(frame.regime_momentum, momentum)
    np.testing.assert_array_equal(frame.regime, np.where(momentum >= p['regime_threshold'], 'bull', 'bear'))
    before, after, flags = state_trace(frame, p)
    threshold = p['confirmation']['threshold']
    values = pd.DataFrame(index=dates)
    values['raw_route'] = frame.regime.to_numpy()
    values['active_route'] = [flag['active'] for flag in flags]
    values['holding_before'] = [state[0] for state in before]
    values['eligible'] = [flag['eligible'] for flag in flags]
    values['opportunity'] = frame.confirmation_opportunity.to_numpy(dtype=bool)
    values['score_pass'] = frame.confirmation_pass.to_numpy(dtype=bool)
    values['entry'] = frame.signal_reason.eq('entry').to_numpy()
    values['target'] = frame.target_position.to_numpy(dtype=float)
    values['signal_close'] = close.reindex(dates).to_numpy()
    values['score'] = score.to_numpy()
    values['threshold'] = threshold
    values['score_margin'] = score.to_numpy()-threshold
    values['absolute_threshold_distance'] = np.abs(values.score_margin)
    for name in normalized:
        values['component_'+name] = normalized[name].to_numpy()
        values['raw_'+name] = raw[name].to_numpy()
    for name, weight in (('acf', .5), ('turnover', .25), ('volume', .25)):
        values['weighted_'+name] = weight*values['component_'+name]
    values['score_equal_features'] = (normalized.acf+normalized.turnover+normalized.volume).to_numpy()/3
    values['score_without_acf'] = (.5*normalized.turnover+.5*normalized.volume).to_numpy()
    assert np.array_equal(values.entry, values.opportunity & values.score_pass)
    return values, before, after


def opportunity_statistics(values):
    columns = ['score', 'score_margin', 'absolute_threshold_distance',
               'component_acf', 'component_turnover', 'component_volume',
               'weighted_acf', 'weighted_turnover', 'weighted_volume',
               'raw_acf', 'raw_turnover', 'raw_volume']
    result = []
    for year in ['ALL', *sorted(set(values.index.year))]:
        year_mask = np.ones(len(values), bool) if year == 'ALL' else values.index.year == year
        for route in ('bull', 'bear'):
            opportunity = np.asarray(year_mask & values.raw_route.eq(route).to_numpy() & values.opportunity.to_numpy(), bool)
            passed = values.score_pass.to_numpy()
            entry = values.entry.to_numpy()
            assert int((opportunity & passed).sum()) == int((year_mask & values.raw_route.eq(route).to_numpy() & entry).sum())
            subsets = {'all_opportunities': opportunity, 'passed': opportunity & passed,
                       'rejected': opportunity & ~passed}
            variants = {}
            for name in ('score_equal_features', 'score_without_acf'):
                alternative = values[name].to_numpy() >= values.threshold.to_numpy()
                variants[name] = {'cross_tab_original_vs_alternative': bool_table(passed[opportunity], alternative[opportunity]),
                                  'alternative_pass_count': int((opportunity & alternative).sum()),
                                  'alternative_score_margin': distribution((values[name]-values.threshold).to_numpy()[opportunity])}
            result.append({'year': str(year), 'route': route, 'native_opportunities': int(opportunity.sum()),
                'passes': int((opportunity & passed).sum()), 'rejections': int((opportunity & ~passed).sum()),
                'exact_threshold_ties': int((opportunity & values.score_margin.eq(0).to_numpy()).sum()),
                'distributions': {group: {column: distribution(values[column].to_numpy()[mask]) for column in columns}
                                  for group, mask in subsets.items()},
                'fixed_weight_predicate_diagnostics': variants})
    assert sum(row['native_opportunities'] for row in result if row['year'] == 'ALL') == int(values.opportunity.sum())
    assert sum(row['native_opportunities'] for row in result if row['year'] != 'ALL') == int(values.opportunity.sum())
    return result


def same_flat_comparison(center, point, center_before, point_before):
    """Complete one-step score/threshold interactions on equal predecision flat states."""
    assert center.index.equals(point.index)
    np.testing.assert_array_equal(center.signal_close, point.signal_close)
    same_flat = np.array([a == b and not a[0] for a, b in zip(center_before, point_before, strict=True)])
    cc = center.score.to_numpy() >= center.threshold.to_numpy()
    cp = center.score.to_numpy() >= point.threshold.to_numpy()
    pc = point.score.to_numpy() >= center.threshold.to_numpy()
    pp = point.score.to_numpy() >= point.threshold.to_numpy()
    assert np.array_equal(cc, center.score_pass) and np.array_equal(pp, point.score_pass)
    ec, ep = center.eligible.to_numpy(), point.eligible.to_numpy()
    assert np.array_equal(center.target.to_numpy()[same_flat], (ec & cc)[same_flat].astype(float))
    assert np.array_equal(point.target.to_numpy()[same_flat], (ep & pp)[same_flat].astype(float))
    rows = []
    for year in ['ALL', *sorted(set(center.index.year))]:
        ymask = np.ones(len(center), bool) if year == 'ALL' else center.index.year == year
        for first_route in ('bull', 'bear'):
            for second_route in ('bull', 'bear'):
                mask = same_flat & ymask & center.raw_route.eq(first_route).to_numpy() & point.raw_route.eq(second_route).to_numpy()
                cross_patterns = Counter(''.join(str(int(column[i])) for column in (cc, cp, pc, pp)) for i in np.flatnonzero(mask))
                interaction = pp.astype(int)-pc.astype(int)-cp.astype(int)+cc.astype(int)
                both_eligible = mask & ec & ep
                entry_disagree = (ec & cc) != (ep & pp)
                combinations = {e+'_'+f+'_'+t: int((mask & eligible & gate).sum())
                    for e, eligible in (('center_eligibility', ec), ('point_eligibility', ep))
                    for f, t, gate in (('center_features', 'center_threshold', cc),
                                       ('center_features', 'point_threshold', cp),
                                       ('point_features', 'center_threshold', pc),
                                       ('point_features', 'point_threshold', pp))}
                rows.append({'year': str(year), 'center_raw_route': first_route, 'point_raw_route': second_route,
                    'same_prestate_flat_days': int(mask.sum()), 'eligibility_disagreement_days': int((mask & (ec != ep)).sum()),
                    'native_score_pass_disagreement_days': int((mask & (cc != pp)).sum()),
                    'native_entry_target_disagreement_days': int((mask & entry_disagree).sum()),
                    'both_base_eligible_days': int(both_eligible.sum()),
                    'both_eligible_score_disagreement_days': int((both_eligible & (cc != pp)).sum()),
                    'native_eligibility_cross_tab': bool_table(ec[mask], ep[mask]),
                    'native_score_cross_tab': bool_table(cc[mask], pp[mask]),
                    'cross_score_pattern_counts_CC_CP_PC_PP': dict(cross_patterns),
                    'feature_change_at_center_threshold_days': int((mask & (cc != pc)).sum()),
                    'feature_change_at_point_threshold_days': int((mask & (cp != pp)).sum()),
                    'threshold_change_on_center_features_days': int((mask & (cc != cp)).sum()),
                    'threshold_change_on_point_features_days': int((mask & (pc != pp)).sum()),
                    'signed_single_step_interaction_counts': {str(k): int((mask & (interaction == k)).sum()) for k in range(-2, 3)},
                    'single_step_entry_predicate_counts': combinations,
                    'score_feature_difference': distribution((point.score-center.score).to_numpy()[mask]),
                    'threshold_difference': distribution((point.threshold-center.threshold).to_numpy()[mask])})
    assert sum(row['same_prestate_flat_days'] for row in rows if row['year'] == 'ALL') == int(same_flat.sum())
    assert sum(row['same_prestate_flat_days'] for row in rows if row['year'] != 'ALL') == int(same_flat.sum())
    return {'groups': rows, 'total_same_prestate_flat_days': int(same_flat.sum()),
            'not_comparable_state_days': int((~same_flat).sum()),
            'scope': 'CC=center features/center threshold,CP=center features/point threshold,PC=point features/center threshold,PP=point features/point threshold. Exact same-flat-strategy-state days only; raw-route disagreements retained as separate groups. Single-step predicates, not new state/cash/profit paths.'}


def main():
    method_reference, method = declared_method()
    assert not OUTPUT.exists(), 'Preserve prior diagnosis output; do not silently overwrite'
    assert not SOURCE_CALLS
    state_trace, verify_account = load_auditors()
    ctx = context(1)
    refs, audits, identities = {}, {}, {}
    try:
        diagnosis_ref = EvidenceRef.from_dict(read(ROOT / 'research/S013/experiments/EX033_20261011/protocols/diagnosis_reference.json'))
        assert diagnosis_ref.to_dict() == method['inputs']['original33'], 'Input manifest must match the declared original33 reference exactly'
        assert file_hash(diagnosis_ref.resolve(ROOT)) == diagnosis_ref.sha256
        prior = read(diagnosis_ref.resolve(ROOT))
        input_refs = prior['input_accounts']
        matrix = read(ROOT / 'research/S013/assets/runs/EX015_20261011/parameter_matrix.json')
        points = sorted((row for row in matrix['rows'] if row['center'] == 'B0-TIME'), key=lambda row: row['point_index'])
        assert len(points) == 32 and [row['point_index'] for row in points] == list(range(32))
        assert set(input_refs) == {'center', *(row['label'] for row in points)}
        transport = next(row for row in cache_read(ROOT / '.tmp/s013-mechanism-EX015/parameters/prepared.pkl.gz') if row['label'] == 'B0-TIME')
        plan = transport['plan']

        def authenticate(label, bound, result):
            reference = EvidenceRef.from_dict(input_refs[label])
            assert reference.experiment.strategy_id == 'S013'
            formal = read(reference.resolve(ROOT))
            validate_evaluation_evidence(formal)
            assert serialize_evaluation_evidence(bound, result) == formal
            identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
            assert result.runs[0].identity == identity
            assert identity.source_sha256 == bound.strategy.payload['runtime']['source_sha256']
            refs[label] = input_refs[label]
            identities[label] = {'candidate_id': bound.strategy.candidate_id, 'content_sha256': identity.content_sha256,
                'source_sha256': identity.source_sha256, 'request_hash': result.request_hash,
                'result_hash': result.result_hash, 'reference_sha256': reference.sha256,
                'runtime_binding_sha256': canonical_sha256(bound.runtime_binding),
                'lineage_sha256': None if bound.lineage is None else canonical_sha256(bound.lineage.to_dict())}
            audits[label] = verify_account(bound, result)
            assert not SOURCE_CALLS

        bound, result = transport['center'], transport['result']
        assert bound.strategy.candidate_id == 'C2132'
        authenticate('center', bound, result)
        assert plan.design.center.content_sha256 == identities['center']['content_sha256']
        original = independently_reconstruct(ctx, bound, result.runs[0].execution.decisions, bound.strategy.payload['parameters'], state_trace)
        center_values, center_before, _ = original
        accounts = {'center': {'candidate_id': 'C2132', 'threshold': bound.strategy.payload['parameters']['confirmation']['threshold'],
                               'statistics': opportunity_statistics(center_values)}}
        paired, pooled = [], [center_values.loc[center_values.opportunity].copy()]
        for row in points:
            label = row['label']
            assert input_refs[label] == row['reference']
            other, account = cache_read(ROOT / '.tmp/s013-mechanism-EX015/parameters' / (label+'.pkl.gz'))
            authenticate(label, other, account)
            assert other.strategy.candidate_id == row['candidate_id']
            assert identities[label]['content_sha256'] == row['content_sha256']
            assert account.request_hash == row['request_hash'] and account.result_hash == row['result_hash']
            assert other.lineage.parameter_binding.point == plan.design.bind_point(row['point_index'])
            parameter_ref = other.lineage.parameter_binding.plan
            assert parameter_ref.experiment.strategy_id == 'S013' and parameter_ref.experiment.experiment_id == 'EX015_20261011'
            assert file_hash(parameter_ref.resolve(ROOT)) == parameter_ref.sha256
            assert read(parameter_ref.resolve(ROOT)) == plan.to_dict()
            derivation = other.lineage.derivation
            assert derivation.kind.value == 'PARAMETERS'
            assert derivation.parent.candidate_id == 'C2132' and derivation.parent_content_sha256 == plan.design.center.content_sha256
            assert derivation.child.candidate_id == row['candidate_id'] and derivation.child_content_sha256 == row['content_sha256']
            values, before, _ = independently_reconstruct(ctx, other, account.runs[0].execution.decisions, other.strategy.payload['parameters'], state_trace)
            assert values.index.equals(center_values.index)
            statistics = opportunity_statistics(values)
            accounts[label] = {'candidate_id': row['candidate_id'], 'point_index': row['point_index'],
                'coordinates': list(other.lineage.parameter_binding.point.coordinates),
                'threshold': other.strategy.payload['parameters']['confirmation']['threshold'], 'statistics': statistics}
            paired.append({'label': label, 'point_index': row['point_index'],
                'same_flat_comparison': same_flat_comparison(center_values, values, center_before, before)})
            pooled.append(values.loc[values.opportunity].copy())
        assert len(refs) == len(accounts) == len(audits) == 33 and refs == input_refs and not SOURCE_CALLS
        pooled_values = pd.concat(pooled, axis=0)
        pooled_statistics = opportunity_statistics(pooled_values)
        all_groups = [group for row in paired for group in row['same_flat_comparison']['groups'] if group['year'] == 'ALL']
        summary = {'native_accounts': 33, 'original_joint_parameter_points': 32, 'native_signal_rows_per_account': len(center_values),
            'native_signal_rows_total': 33*len(center_values), 'center_statistics': accounts['center']['statistics'],
            'pooled_native_opportunity_statistics': pooled_statistics,
            'pooled_interpretation': 'Repeated, dependent same-S013 native account opportunity observations, not independent samples.',
            'paired_same_flat_totals': {name: sum(group[name] for group in all_groups) for name in (
                'same_prestate_flat_days', 'eligibility_disagreement_days', 'native_score_pass_disagreement_days',
                'native_entry_target_disagreement_days', 'both_base_eligible_days', 'both_eligible_score_disagreement_days')},
            'fixed_weights': {'native': {'acf': .5, 'turnover': .25, 'volume': .25},
                             'equal_features': {'acf': 1/3, 'turnover': 1/3, 'volume': 1/3},
                             'without_acf': {'acf': 0., 'turnover': .5, 'volume': .5}},
            'new_account_evaluations': 0, 'cash_replays': 0, 'provider_calls': list(SOURCE_CALLS)}
        output = {'status': 'PASS', 'new_account_evaluations': 0, 'input_accounts': refs, 'account_audits': audits,
            'summary': summary, 'limits': LIMITS, 'method_reference': method_reference,
            'prior_input_manifest_reference': diagnosis_ref.to_dict(), 'native_identity_audits': identities,
            'feature_audit': 'All33 original bound full histories: independent OHLC/rawACF20/both ranges/momentum/raw regime/amount-volume features/causal ranks/.5-.25-.25 score; native opportunity/pass/entry/target/all original state transitions exact.',
            'distribution_method': 'LINEAR quantiles1/3,1/2,2/3,min,max,mean; empty groups count0/null, no new gate or distance cutoff.',
            'accounts': accounts, 'points': paired, 'declared_method_name': method.get('name')}
        write(OUTPUT, output)
        print({'confirmation_diagnosis': 'PASS', 'native_accounts': len(refs), 'new_account_evaluations': 0,
               'output': str(OUTPUT.relative_to(ROOT))}, flush=True)
    except Exception as error:
        assert not OUTPUT.exists()
        write(OUTPUT, {'status': 'FAILED', 'new_account_evaluations': 0, 'input_accounts': refs, 'account_audits': audits,
            'summary': {'authenticated_accounts': len(refs), 'provider_calls': list(SOURCE_CALLS)},
            'limits': LIMITS, 'method_reference': method_reference,
            'error': {'type': type(error).__name__, 'message': str(error)},
            'policy': 'Failure retained; no provider download/fallback, replacement, partial PASS or automatic retry.'})
        raise


if __name__ == '__main__':
    main()
