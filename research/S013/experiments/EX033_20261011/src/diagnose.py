"""Exact native-account exit/reentry diagnosis; zero new account evaluations."""
# ruff: noqa: E402
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
PRIOR = ROOT / 'research/S013/experiments/EX032_20261011/src'
sys.path.insert(0, str(PRIOR))
from common import context, read, write, cache_read, file_hash
from run_parameters import resolve_center, get_path
from account_reference import verify_account
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from collections import Counter
import json
import numpy as np
import pandas as pd

EXPERIMENT = ExperimentRef('S013', SRC.parent.name)
PROTO = SRC.parent / 'protocols'
RUNS = ROOT / 'research/S013/assets/runs' / EXPERIMENT.experiment_id


def state_trace(frame, p):
    """Reconstruct original states from native features; no synthetic cash replay."""
    assert p['context']['entry_gate'] == 'all' and p['confirmation']['scope'] == 'both'
    assert p['exit_on_regime_change'] is True
    for route in ('bull', 'bear'):
        assert p[route]['stop_loss'] is None and p[route]['trailing_stop'] is None
        assert p[route]['cooldown'] == 0
    holding = False
    route = None
    age = 0
    states, before, flags = [], [], []
    for row in frame.itertuples():
        before.append((holding, route, age if holding else 0))
        active = route if holding else row.regime
        rp = p[active]
        position = getattr(row, active + '_range_position')
        assert position == row.range_position
        predicates = {'range': bool(position >= rp['exit']),
                      'time': bool(holding and age + 1 >= rp['max_hold']),
                      'regime': bool(holding and row.regime != route)}
        eligible = (position <= rp['entry'] and
                    (rp['acf_min'] is None or row.acf1 >= rp['acf_min']) and
                    (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
        passed = row.confirmation_score >= p['confirmation']['threshold']
        assert bool(row.confirmation_opportunity) == bool(not holding and eligible)
        assert bool(row.confirmation_pass) == bool(passed)
        reason = 'flat'
        if holding:
            age += 1
            reason = ('range' if predicates['range'] else 'time' if predicates['time']
                      else 'regime' if predicates['regime'] else 'hold')
            if reason != 'hold':
                holding, route = False, None
        elif eligible:
            reason = 'entry' if passed else 'confirmation_rejected'
            if passed:
                holding, route, age = True, row.regime, 0
        assert row.signal_reason == reason and row.target_position == float(holding)
        flags.append({**predicates, 'eligible': bool(eligible), 'confirmed': bool(passed),
                      'active': active, 'age_before': before[-1][2]})
        states.append((holding, route, age if holding else 0))
    return before, states, flags


def reentries(frame, before):
    reasons = frame.signal_reason.to_numpy()
    entries = np.flatnonzero(reasons == 'entry')
    rows = []
    for i in np.flatnonzero(np.isin(reasons, ['time', 'range', 'regime'])):
        later = entries[entries > i]
        j = int(later[0]) if len(later) else None
        route = before[i][1]
        rows.append({'exit_index': int(i), 'exit_date': str(frame.signal_date.iloc[i]),
                     'exit_reason': str(reasons[i]), 'active_route': route,
                     'next_entry_index': j, 'waiting_sessions': None if j is None else j - int(i),
                     'next_entry_route': None if j is None else str(frame.regime.iloc[j]),
                     'same_route': bool(j is not None and frame.regime.iloc[j] == route),
                     'unbroken_raw_route': bool(j is not None and (frame.regime.iloc[i:j+1] == route).all())})
    counts = []
    for route in ('bull', 'bear'):
        for reason in ('time', 'range', 'regime'):
            group = [r for r in rows if r['active_route'] == route and r['exit_reason'] == reason]
            counts.append({'route': route, 'reason': reason, 'exits': len(group),
                           'next_session_same_route_entry': sum(r['waiting_sessions'] == 1 and r['same_route'] for r in group),
                           'next_session_unbroken_route_entry': sum(r['waiting_sessions'] == 1 and r['unbroken_raw_route'] for r in group),
                           'within_two_same_route_entry': sum(r['waiting_sessions'] is not None and r['waiting_sessions'] <= 2 and r['same_route'] for r in group)})
    return {'groups': counts, 'events': rows}


def episodes(center, point, cstates, pstates, cbefore, pbefore, cflags, pflags):
    difference = np.array([a != b for a, b in zip(cstates, pstates, strict=True)])
    target = center.target_position.to_numpy() != point.target_position.to_numpy()
    assert np.all(~target | difference)
    rows = []
    i = 0
    while i < len(center):
        if not difference[i]:
            i += 1
            continue
        start = i
        assert cbefore[i] == pbefore[i]
        while i < len(center) and difference[i]:
            i += 1
        end = i
        reason_pair = str(center.signal_reason.iloc[start]) + '->' + str(point.signal_reason.iloc[start])
        initiator = 'holding_exit' if cbefore[start][0] else 'flat_entry'
        changes = [key for key in ('range', 'time', 'regime', 'eligible', 'confirmed')
                   if cflags[start][key] != pflags[start][key]]
        if center.regime.iloc[start] != point.regime.iloc[start]:
            changes.append('raw_regime')
        rows.append({'start_index': start, 'start_date': str(center.signal_date.iloc[start]),
                     'last_different_index': end - 1, 'state_difference_sessions': end - start,
                     'resynchronized_index': end if end < len(center) else None,
                     'resynchronized_kind': ('FLAT' if not cstates[end][0] else 'SAME_ROUTE_AND_AGE') if end < len(center) else 'OPEN_TAIL',
                     'initiator': initiator, 'reason_pair': reason_pair, 'changed_predicates': changes,
                     'time_in_reason_pair': 'time' in reason_pair,
                     'different_target_sessions': int(target[start:end].sum()),
                     'center_entries_inside': int(center.signal_reason.iloc[start:end].eq('entry').sum()),
                     'point_entries_inside': int(point.signal_reason.iloc[start:end].eq('entry').sum())})
    assert sum(r['state_difference_sessions'] for r in rows) == int(difference.sum())
    assert sum(r['different_target_sessions'] for r in rows) == int(target.sum())
    lengths = [r['state_difference_sessions'] for r in rows]
    counts = Counter(r['reason_pair'] for r in rows)
    return {'episodes': rows, 'count': len(rows), 'reason_pairs': dict(counts),
            'time_seeded_episodes': sum(r['time_in_reason_pair'] for r in rows),
            'state_different_days': int(difference.sum()), 'target_different_days': int(target.sum()),
            'state_difference_without_target_difference_days': int((difference & ~target).sum()),
            'duration_median': float(np.median(lengths)), 'duration_q90': float(np.quantile(lengths, .9)),
            'duration_max': max(lengths), 'both_flat_resynchronizations': sum(r['resynchronized_kind'] == 'FLAT' for r in rows),
            'same_holding_resynchronizations': sum(r['resynchronized_kind'] == 'SAME_ROUTE_AND_AGE' for r in rows)}


def log_gap(center, point):
    a, b = center.execution.account_daily, point.execution.account_daily
    np.testing.assert_array_equal(a.date, b.date)
    ad, bd = np.asarray(a.equity, float), np.asarray(b.equity, float)
    ar = np.log(ad / np.r_[1_000_000., ad[:-1]])
    br = np.log(bd / np.r_[1_000_000., bd[:-1]])
    invested_a, invested_b = a.quantity.to_numpy() > 0, b.quantity.to_numpy() > 0
    groups = np.where(invested_a, np.where(invested_b, 'BOTH_INVESTED', 'ONLY_CENTER'),
                      np.where(invested_b, 'ONLY_POINT', 'BOTH_FLAT'))
    years = pd.to_datetime(a.date).dt.year.to_numpy()
    results = {}
    for year in sorted(set(years)):
        mask = years == year
        indexes = np.flatnonzero(mask)
        opening_a = 1_000_000. if indexes[0] == 0 else ad[indexes[0] - 1]
        opening_b = 1_000_000. if indexes[0] == 0 else bd[indexes[0] - 1]
        exact = np.log(bd[indexes[-1]] / opening_b) - np.log(ad[indexes[-1]] / opening_a)
        sums = {g: float((br-ar)[mask & (groups == g)].sum())
                for g in ('BOTH_INVESTED', 'ONLY_CENTER', 'ONLY_POINT', 'BOTH_FLAT')}
        assert abs(sum(sums.values()) - exact) < 1e-12
        results[str(year)] = {'log_return_gap': float(exact), 'groups': sums,
                             'days': {g: int((mask & (groups == g)).sum()) for g in sums},
                             'center_return': float(ad[indexes[-1]] / opening_a - 1),
                             'point_return': float(bd[indexes[-1]] / opening_b - 1)}
    return results


def declare():
    assert not (PROTO / 'plan.json').exists()
    matrix = read(ROOT/'research/S013/assets/runs/EX015_20261011/parameter_matrix.json')
    entries = sorted((r for r in matrix['rows'] if r['center'] == 'B0-TIME'), key=lambda r:r['point_index'])
    assert len(entries) == 32 and [r['point_index'] for r in entries] == list(range(32))
    center = read(ROOT/'research/S013/assets/runs/EX032_20261011/account_references.json')['B0-TIME']
    plan = {'name': 'S013-EX033-native-exit-reentry-diagnosis', 'new_account_evaluations': 0,
            'center_reference': center, 'points': entries,
            'authorization': read(PRIOR.parent/'protocols/authorization.json'),
            'mandate': read(PRIOR.parent/'protocols/plan.json')['mandate'],
            'previous_delivery': read(PRIOR.parent/'protocols/delivery_reference.json'),
            'source_files': {'src/diagnose.py': file_hash(SRC/'diagnose.py')},
            'method': 'Original 33 full native accounts exact reuse; original signal-state = (holding, active_route, age), because stops/trail/cooldown disabled and all-entry confirmation ignores last-exit context. State resynchronization does not equate perturbed future predicates or inherited cash. Enumerate maximal different-state segments seeded from same pre-state, reason/predicate disagreement and reentries; sums of daily log-return differences by same-date actual closing invested flags telescope exactly to annual log-return differences.',
            'limits': 'Posthoc repeatedly seen S013 development pool; joint parameters, not single-parameter causal attribution. No account replay, simulated profit, timing optimization, new gate or guarantee. Native confirmation score/range features reused and state predicates verified, not all features independently rebuilt from OHLC.',
            'selection': 'No year/date/cycle discarded; all 32 existing original complete-domain points. Report every natural year; 2022/2023 were preexisting economic years.'}
    write(PROTO/'plan.json', plan)
    ref = publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT,'declared-path-method',(PROTO/'plan.json').read_bytes(),'application/json','json'))
    write(PROTO/'plan_reference.json',ref.to_dict())
    print({'method': 'DECLARED', 'native_accounts': 33, 'new_evaluations': 0}, flush=True)


def main():
    plan = read(PROTO/'plan.json')
    assert file_hash(SRC/'diagnose.py') == plan['source_files']['src/diagnose.py']
    assert not (PROTO/'diagnosis_reference.json').exists()
    original = next(c for c in read(PRIOR.parent/'protocols/plan.json')['controls'] if c['label'] == 'B0-TIME')
    bound, result = resolve_center(original)
    center = result.runs[0]
    frames = center.execution.decisions
    p = bound.strategy.payload['parameters']
    assert bound.strategy.candidate_id == 'C2132'
    assert result.runs[0].identity.content_sha256 == original['content_sha256']
    ctx = context(1)
    refs, audits = {}, {}

    def authenticate(label, binding, account, refdict):
        ref = EvidenceRef.from_dict(refdict)
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
        actual = read(ref.resolve(ROOT))
        validate_evaluation_evidence(actual)
        assert actual == serialize_evaluation_evidence(binding, account)
        identity = ctx.runtime.identify(binding.strategy, dependencies=binding.dependencies)
        assert identity.content_sha256 == account.runs[0].identity.content_sha256
        refs[label] = refdict
        audits[label] = verify_account(binding, account)

    authenticate('center', bound, result, plan['center_reference'])
    cbefore, cstates, cflags = state_trace(frames, p)
    rows = []
    geometry = read(ROOT/'research/S013/experiments/EX015_20261011/protocols/geometry.json')
    for item in plan['points']:
        other, account = cache_read(ROOT/'.tmp/s013-mechanism-EX015/parameters'/(item['label']+'.pkl.gz'))
        authenticate(item['label'], other, account, item['reference'])
        assert other.lineage.parameter_binding.point.point_index == item['point_index']
        assert other.strategy.candidate_id == item['candidate_id']
        assert account.runs[0].identity.content_sha256 == item['content_sha256']
        point = account.runs[0]
        native = point.execution.decisions
        np.testing.assert_array_equal(native.signal_date, frames.signal_date)
        np.testing.assert_array_equal(native.close, frames.close)
        q = other.strategy.payload['parameters']
        pbefore, pstates, pflags = state_trace(native, q)
        row = {'point_index': item['point_index'], 'candidate_id': item['candidate_id'],
               'changes': {name: {'before': get_path(p,name), 'after': get_path(q,name)}
                           for name,*_ in geometry['coordinates'] if get_path(p,name) != get_path(q,name)},
               'state_episodes': episodes(frames,native,cstates,pstates,cbefore,pbefore,cflags,pflags),
               'reentries': reentries(native,pbefore), 'annual_log_gap': log_gap(center,point)}
        rows.append(row)
    pair_counts = Counter()
    for r in rows:
        pair_counts.update(r['state_episodes']['reason_pairs'])
    summary = {'points':32, 'episodes':sum(r['state_episodes']['count'] for r in rows),
               'reason_pairs': dict(pair_counts), 'time_seeded_episodes':sum(r['state_episodes']['time_seeded_episodes'] for r in rows),
               'mean_state_different_days':float(np.mean([r['state_episodes']['state_different_days'] for r in rows])),
               'mean_target_different_days':float(np.mean([r['state_episodes']['target_different_days'] for r in rows])),
               'longest_state_episode':max(r['state_episodes']['duration_max'] for r in rows),
               'mean_annual_log_gap':{str(year):{g:float(np.mean([r['annual_log_gap'][str(year)]['groups'][g] for r in rows]))
                                              for g in ('BOTH_INVESTED','ONLY_CENTER','ONLY_POINT','BOTH_FLAT')}
                                      for year in range(2020,2027)}}
    output = {'status':'PASS', 'new_account_evaluations':0, 'input_accounts':refs, 'account_audits':audits,
              'center_reentries':reentries(frames,cbefore), 'points':rows, 'summary':summary,
              'method_reference':read(PROTO/'plan_reference.json'), 'limits':plan['limits'],
              'economic_targets':'UNCHANGED', 'objective_achieved':False}
    write(RUNS/'diagnosis.json',output)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT,'native-exit-reentry-diagnosis',(RUNS/'diagnosis.json').read_bytes(),'application/json','json'))
    write(PROTO/'diagnosis_reference.json',ref.to_dict())
    print(json.dumps({'summary':summary,'center_reentries':output['center_reentries']['groups']},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    declare() if sys.argv[1:] == ['declare'] else main()
