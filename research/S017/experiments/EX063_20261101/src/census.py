"""Source/protocol/feature-locked opening event census; no new execution paths."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import json
from pathlib import Path
from statistics import mean, median

from common import ROOT, WORK, INPUT_SHA, LABEL_SHA, checked_bytes, digest, read, save

H = (3, 13, 26, 65, 130)
GROUPS = ('G0', 'G1', 'OLD_M025', 'G0_WITHOUT_G1', 'G1_NEW_NOT_M025')
CONTRACT = {
    'schema': 's017-opening-acceptance-census/v1', 'experiment_id': 'EX063_20261101',
    'train_start': '2024-01-02', 'train_end': '2025-12-31', 'horizons': list(H), 'groups': list(GROUPS),
    'universe': 'All502 exact planned first complete RTH M30 observations;previous observed Date equals previous planned RTH last end;any missing requirement fails.',
    'G0': 'first Low>previous planned session Close;strict equality rejects',
    'G1': 'G0 AND first Close>Open',
    'OLD_M025': 'first Open>=priorClose+lag1 simpleATR13 AND first Close>Open',
    'G0_WITHOUT_G1': 'G0 AND NOT G1;includes doji',
    'G1_NEW_NOT_M025': 'G1 AND NOT OLD_M025;diagnostic new coverage,not new trading filter',
    'ordinary': 'COMMON_ALL5 first openings excluding ALL_RAW union(G0,OLD_M025)',
    'inner': {'G1': 'G0_WITHOUT_G1', 'G1_NEW_NOT_M025': 'OLD_M025'},
    'matching': ['planned_entry_year_month', 'planned_entry_America_New_York_slot'],
    'sparse': 'No widening,fallback,self-inclusion or zero imputation;all-target mean and supported subset separate',
    'nonoverlap': 'Chronological RAW signals select next old label index>previous+131,THEN common all5;never replace failed/unmature events',
    'yearly': 'Slice same selected common cohort by signal year;never reselect or use future year as entry gate',
    'cost': 'one-share oldEX020 nextinterval1pct tickfloor/strictLow touch buy,.001eachside,nextinterval market exit',
    'members': 'common-complete diagnostic eligibility is never a trading filter',
    'interpretation': 'Horizon is diagnostic,not exit clock;G0 vsordinary whole-event association,not pure no-fill causal;G1 vsinner conditional association',
    'input_sha256': INPUT_SHA, 'execution_label_sha256': LABEL_SHA,
    'new_execution_labels': 0, 'new_full_strategy_account_compute': 0, 'sealed_test_access': False,
}


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def verify_lock():
    proof_path = WORK / 'others/census_pre_run.json'
    public = read(WORK / 'others/pre_label_publication.json')
    proof_bytes = checked_bytes(public['lock'])
    if proof_bytes != proof_path.read_bytes():
        raise ValueError('Public lock bytes do not match current proof')
    proof = json.loads(proof_bytes)
    if proof['status'] != 'LOCKED_PRE_LABEL':
        raise ValueError('Pre-label lock required')
    for key, name in (('common_source', 'common.py'), ('feature_source', 'features.py'), ('census_source', 'census.py')):
        if checked_bytes(proof[key]) != (WORK / 'src' / name).read_bytes():
            raise ValueError('Locked program changed: ' + name)
    if json.loads(checked_bytes(proof['contract'])) != CONTRACT:
        raise ValueError('Locked census contract changed')
    feature = json.loads(checked_bytes(proof['features']))
    if feature['status'] != 'PASS_OUTCOME_BLIND_OPENING_FEATURES' or feature['new_future_labels_or_group_returns'] != 0:
        raise ValueError('Outcome-blind features required')
    if feature['input_ref']['sha256'] != INPUT_SHA or feature['source_sha256'] != proof['feature_source']['sha256']:
        raise ValueError('Feature input/source identity changed')
    if proof['execution_labels']['sha256'] != LABEL_SHA or proof['execution_labels']['experiment']['experiment_id'] != 'EX020_20261029':
        raise ValueError('Original execution label source required')
    return proof, feature, digest(proof_path)


def stats(values):
    return {'n': len(values), 'net_mean': mean(values) if values else None,
        'net_median': median(values) if values else None,
        'positive_fraction': sum(x > 0 for x in values) / len(values) if values else None}


def matched(grid, targets, controls):
    if set(targets) & set(controls):
        raise ValueError('Self-containing control prohibited')
    cells = defaultdict(list)
    for i in controls:
        cells[grid[i]['stratum']].append(grid[i]['price_net_return'])
    averages = {k: mean(v) for k, v in cells.items()}
    supported = [i for i in targets if grid[i]['stratum'] in averages]
    return {'all_target_own': stats([grid[i]['price_net_return'] for i in targets]),
        'control_population': len(controls), 'supported_targets': len(supported),
        'unsupported_targets': len(targets) - len(supported),
        'support_fraction': len(supported) / len(targets) if targets else None,
        'supported_own_mean': mean(grid[i]['price_net_return'] for i in supported) if supported else None,
        'matched_control_mean': mean(averages[grid[i]['stratum']] for i in supported) if supported else None,
        'matched_difference': mean(grid[i]['price_net_return'] - averages[grid[i]['stratum']] for i in supported) if supported else None,
        'minimum_control_count': min((len(cells[grid[i]['stratum']]) for i in supported), default=None),
        'supported_indices': supported, 'unsupported_indices': sorted(set(targets) - set(supported))}


def panel(grids, members, ordinary, inner):
    return {str(h): {'ordinary': matched(grids[h], members, ordinary),
        'inner': matched(grids[h], members, inner) if inner is not None else {'applicable': False}}
        for h in H}


def continuation(grids, members):
    return {f'{a}_to_{b}': {'n': len(members),
        'same_initial_capital_mean_net_difference': mean(grids[b][i]['price_net_return'] - grids[a][i]['price_net_return'] for i in members) if members else None}
        for a, b in ((3, 13), (13, 26), (26, 65), (65, 130))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-contract', action='store_true')
    parser.add_argument('--check-lock-only', action='store_true')
    args = parser.parse_args()
    if args.write_contract:
        save(WORK / 'protocols/census_contract.json', CONTRACT)
        return
    proof, feature, lock_sha = verify_lock()
    if args.check_lock_only:
        print('PUBLIC_LOCK_PASS;NO_LABEL_BYTES_READ', flush=True)
        return
    # First return-label bytes access occurs only after the complete public lock check.
    decoded = json.loads(gzip.decompress(checked_bytes(proof['execution_labels'])))
    labels = [r for r in decoded if CONTRACT['train_start'] <= r['signal_at'][:10] <= CONTRACT['train_end']]
    del decoded
    grids = {h: {} for h in H}
    fee_checks = 0
    for r in labels:
        if r['n'] not in H or r['i'] in grids[r['n']]:
            raise ValueError('Unique original horizon/index rows required')
        grids[r['n']][r['i']] = r
        if r['status'] == 'COMPLETE':
            expected = r['exit_price'] * .999 / (r['entry_price'] * 1.001) - 1
            if abs(expected - r['price_net_return']) > 1e-12:
                raise ValueError('Original fee arithmetic mismatch')
            fee_checks += 1
        elif r['price_net_return'] is not None:
            raise ValueError('Unmatured return must not be imputed')
    universe = set(grids[3])
    if len(universe) != 6489 or any(set(grids[h]) != universe for h in H):
        raise ValueError('Original training clock changed')
    clock = {at(r['signal_at']): i for i, r in grids[3].items()}
    groups = {g: set() for g in GROUPS}
    opening = set()
    joins = []
    for row in feature['feature_rows']:
        stamp = at(row['signal_at'])
        if stamp not in clock:
            raise ValueError('First opening missing from original label clock')
        i = clock[stamp]
        opening.add(i)
        joins.append({'signal_at': row['signal_at'], 'current_input_index': row['bar_index'], 'old_label_index': i})
        for g in GROUPS:
            if row[g]:
                groups[g].add(i)
    if len(opening) != 502:
        raise ValueError('All first openings must map uniquely')
    common = {i for i in universe if all(grids[h][i]['status'] == 'COMPLETE' for h in H)}
    ordinary = (opening & common) - groups['G0'] - groups['OLD_M025']
    results = {}
    for g, raw in groups.items():
        all_common = sorted(raw & common)
        selected = []
        for i in sorted(raw):
            if not selected or i > selected[-1] + 131:
                selected.append(i)
        thin = sorted(set(selected) & common)
        inner_name = CONTRACT['inner'].get(g)
        inner = (groups[inner_name] & common) if inner_name else None
        maturity = {}
        for h in H:
            complete = [i for i in raw if grids[h][i]['status'] == 'COMPLETE']
            maturity[str(h)] = {'statuses': dict(Counter(grids[h][i]['status'] for i in raw)),
                'all_complete_own': stats([grids[h][i]['price_net_return'] for i in complete])}
        results[g] = {'raw': len(raw), 'common': len(all_common), 'fixed130_preselected': len(selected),
            'fixed130_common': len(thin), 'raw_indices': sorted(raw), 'common_indices': all_common,
            'preselected_indices': selected, 'thin_indices': thin, 'maturity': maturity,
            'common_raw': panel(grids, all_common, ordinary, inner),
            'common_thin': panel(grids, thin, ordinary, inner),
            'continuation_raw': continuation(grids, all_common), 'continuation_thin': continuation(grids, thin),
            'years': {year: {'raw': panel(grids, [i for i in all_common if grids[3][i]['signal_at'].startswith(year)], ordinary, inner),
                'thin': panel(grids, [i for i in thin if grids[3][i]['signal_at'].startswith(year)], ordinary, inner)}
                for year in ('2024', '2025')}}
    out = {'status': 'PASS_FIXED_OPENING_ACCEPTANCE_CENSUS', 'source_sha256': digest(Path(__file__)),
        'public_lock_sha256': lock_sha, 'public_lock_verified_before_label_bytes': True,
        'contract': CONTRACT, 'lock': proof, 'training_label_clock': len(universe),
        'opening_universe': len(opening), 'opening_common': len(opening & common),
        'ordinary_population': len(ordinary), 'fee_arithmetic_rows': fee_checks,
        'timestamp_to_index_join': joins, 'results': results,
        'same_training_reused_not_independent': True, 'new_account_compute': 0,
        'new_execution_labels': 0, 'new_data_downloads': 0, 'sealed_2026_access': False}
    save(WORK / 'others/census_result.json', out)
    print('LOCKED_OPENING_CENSUS_PASS', {g: {k: results[g][k] for k in ('raw', 'common', 'fixed130_common')} for g in GROUPS}, flush=True)


if __name__ == '__main__':
    main()
