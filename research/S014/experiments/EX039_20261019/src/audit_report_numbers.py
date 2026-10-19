"""Independent saved-prediction arithmetic only; no model imports or fits."""
import json
from pathlib import Path
from hashlib import sha256

import numpy as np
import pandas as pd

ROOT = Path.cwd()
EX = ROOT / 'research/S014/experiments/EX039_20261019'
OUT = EX / 'others'
saved = json.loads((OUT / 'fixed_analysis/analysis.json').read_bytes())
p = pd.read_csv(OUT / 'fixed_analysis/predictions.csv')
inputs = pd.read_csv(OUT / 'model_inputs.csv').set_index('signal')
inputs['date'] = pd.to_datetime(inputs.date)
assert not p.duplicated(['family', 'model', 'signal']).any()
checks = []
results = {}


def truth(values):
    mapped = values.astype(str).str.lower().map({'true': True, 'false': False})
    assert mapped.notna().all()
    return mapped.to_numpy(bool)


def measures(f, base, new):
    y = f.Y3.to_numpy(float)
    l = np.maximum(-y, 0)
    b, n = f['keep_' + base].to_numpy(bool), f['keep_' + new].to_numpy(bool)
    removed, added = b & ~n, n & ~b
    mi = (l - f['score_' + base].to_numpy(float))**2 - (l - f['score_' + new].to_numpy(float))**2
    ad = (n.astype(int) - b.astype(int)) * y
    components = [np.maximum(-y, 0) * removed, -np.maximum(y, 0) * removed,
                  np.maximum(y, 0) * added, -np.maximum(-y, 0) * added]
    np.testing.assert_allclose(np.sum(components, axis=0), ad, atol=1e-15, rtol=0)
    return {'n': len(f), 'mse_improvement': float(mi.mean()), 'allocation_difference_per_evaluable_A': float(ad.mean()),
            'mse_improvement_percent': float(100 * mi.mean() / np.mean((l - f['score_' + base].to_numpy(float))**2)),
            'removed_n': int(removed.sum()), 'added_n': int(added.sum()),
            'reduced_losses_removed': float(components[0].mean()), 'foregone_positive_removed': float(-components[1].mean()),
            'added_positive': float(components[2].mean()), 'added_losses': float(-components[3].mean())}, mi, ad


def diagnostics(f, base, new):
    result, mi, ad = measures(f, base, new)
    labels, group, endpoint = {}, -1, -1
    for row in f[f.entry_filled].sort_values(['entry', 'maturity', 'signal']).itertuples():
        if row.entry > endpoint:
            group += 1
        labels[row.signal] = group
        endpoint = max(endpoint, row.maturity)
    for row in f[~f.entry_filled].itertuples():
        group += 1
        labels[row.signal] = group
    cluster = np.array([labels[int(i)] for i in f.signal])
    unique = np.unique(cluster)
    result['cluster_count'] = len(unique)
    totals = np.array([[mi[cluster == c].sum(), ad[cluster == c].sum(), (cluster == c).sum()] for c in unique])
    absolute = abs(totals[:, 1]).sum()
    result['largest_cluster_share_of_absolute_allocation_contribution'] = None if absolute == 0 else float(abs(totals[:, 1]).max() / absolute)
    biggest = unique[np.argmax(abs(totals[:, 1]))]
    result['largest_absolute_allocation_cluster_removed'] = measures(f[cluster != biggest], base, new)[0]
    result['equal_cluster'] = {'mse_improvement': float(np.mean(totals[:, 0] / totals[:, 2])),
                               'allocation_difference_per_evaluable_A': float(np.mean(totals[:, 1] / totals[:, 2]))}
    selected, endpoint = [], -1
    for row in f.sort_values('signal').itertuples():
        if not row.entry_filled:
            selected.append(row.signal)
        elif row.entry > endpoint:
            selected.append(row.signal)
            endpoint = row.maturity
    result['chronological_nonoverlap'] = measures(f[f.signal.isin(selected)], base, new)[0]
    rng = np.random.default_rng(13)
    samples = np.empty((2000, 2))
    for i in range(2000):
        chosen = rng.choice(len(unique), len(unique), replace=True)
        summed = totals[chosen].sum(axis=0)
        samples[i] = summed[:2] / summed[2]
    result['bootstrap_intervals'] = {
        'mse_improvement': np.quantile(samples[:, 0], [.025, .975]).tolist(),
        'allocation_difference_per_evaluable_A': np.quantile(samples[:, 1], [.025, .975]).tolist(),
    }
    matched = np.zeros(len(f), bool)
    for _, yearly in f.groupby(f.date.dt.year):
        k = int(yearly['keep_' + new].sum())
        selected_idx = yearly.sort_values(['score_' + base, 'signal']).index[:k]
        matched[f.index.get_indexer(selected_idx)] = True
    result['matched_allocation_difference'] = float(np.mean(f.Y3.to_numpy(float) * (f['keep_' + new].to_numpy(int) - matched.astype(int))))
    return result


def compare(actual, expected, prefix):
    for name in ['n', 'mse_improvement', 'allocation_difference_per_evaluable_A', 'removed_n', 'added_n',
                 'reduced_losses_removed', 'foregone_positive_removed', 'added_positive', 'added_losses', 'cluster_count']:
        np.testing.assert_allclose(actual[name], expected[name], atol=2e-14, rtol=0, err_msg=prefix + ':' + name)
    for name in ['equal_cluster', 'largest_absolute_allocation_cluster_removed', 'chronological_nonoverlap']:
        for metric in ['mse_improvement', 'allocation_difference_per_evaluable_A']:
            np.testing.assert_allclose(actual[name][metric], expected[name][metric], atol=2e-14, rtol=0, err_msg=prefix + ':' + name)
    for metric, interval in actual['bootstrap_intervals'].items():
        np.testing.assert_allclose(interval, expected['cluster_bootstrap']['intervals'][metric], atol=2e-14, rtol=0)
    np.testing.assert_allclose(actual['matched_allocation_difference'], expected['posthoc_matched_participation']['new_minus_matched_allocation'], atol=2e-14, rtol=0)
    checks.append(prefix)


for family, base, comparisons in [('ETF', 'E0', ['E1', 'E2']), ('OPTION', 'O0', ['O1']), ('JOINT', 'J0', ['J1'])]:
    subset = p[p.family.eq(family)]
    f = inputs.loc[sorted(subset.signal.unique())].reset_index()
    assert truth(f.A).all()
    f['entry_filled'] = truth(f.entry_filled)
    for model, g in subset.groupby('model'):
        assert set(g.signal) == set(f.signal)
        g = g.set_index('signal')
        f['score_' + model] = f.signal.map(g.score)
        f['keep_' + model] = truth(f.signal.map(g.keep))
        np.testing.assert_allclose(f.Y3, f.signal.map(g.Y3), atol=1e-15, rtol=0)
    results[family] = {}
    for new in comparisons:
        pair = new + '_minus_' + base
        results[family][pair] = {}
        for view, data in [('all_evaluation', f), ('without_2026', f[f.year.lt(2026)])]:
            actual = diagnostics(data, base, new)
            compare(actual, saved['families'][family]['comparisons'][view][pair], family + ':' + pair + ':' + view)
            results[family][pair][view] = actual
        for year in [2023, 2024, 2025, 2026]:
            actual = measures(f[f.year.eq(year)], base, new)[0]
            expected = saved['families'][family]['years'][str(year)]['comparisons'][pair]
            for metric in ['n', 'mse_improvement', 'allocation_difference_per_evaluable_A']:
                np.testing.assert_allclose(actual[metric], expected[metric], atol=2e-14, rtol=0)
            results[family][pair][str(year)] = actual
    if family != 'ETF':
        results[family]['active_pair_count'] = int(truth(f.opt_active_pair).sum())
        results[family]['roll_count'] = int(truth(f.opt_roll).sum())

coefficients = []
for year in [2023, 2024, 2025, 2026]:
    entry = saved['families']['OPTION']['years'][str(year)]['coefficients']['O1']['opt_delta_put']
    assert entry < 0
    coefficients.append(entry)
review = {'status': 'PASS', 'method': 'Independent saved prediction arithmetic and inclusive overlap-cluster total resampling; no analyze_fixed import and no coefficient estimation/fit',
          'paired_views_recomputed': checks, 'annual_views_recomputed': 16, 'option_coefficients': coefficients,
          'numbers': results, 'new_fits': 0, 'new_calls': 0,
          'source_hashes': {str(path.relative_to(ROOT)).replace('\\', '/'): sha256(path.read_bytes()).hexdigest() for path in
                            [OUT / 'fixed_analysis/predictions.csv', OUT / 'fixed_analysis/analysis.json', OUT / 'model_inputs.csv']}}
target = ROOT / '.tmp/ex039_report_numeric_review_result.json'
with target.open('x', encoding='utf-8') as handle:
    json.dump(review, handle, ensure_ascii=False, indent=2, allow_nan=False)
print(json.dumps({'status': 'PASS', 'paired_views': len(checks), 'annual_views': 16, 'new_fits': 0}))
