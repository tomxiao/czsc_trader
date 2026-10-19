"""Audit immutable EX039 saved scores with Decimal arithmetic; never fit models."""
import csv
import hashlib
import json
from datetime import datetime
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 45
ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
EX = Path('research/S014/experiments/EX039_20261019')
D = Decimal
TOL = D('1e-12')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'), parse_float=D)


def dump(name, value):
    def normalize(x):
        if isinstance(x, D):
            return float(x)
        raise TypeError(type(x).__name__)
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                     default=normalize) + '\n', encoding='utf-8')


def mean(items):
    values = list(items)
    return sum(values, D(0)) / len(values)


result = read_json(ROOT / EX / 'others/result.json')
receipt = read_json(ROOT / 'research/S014/deliveries/COMPONENTS/22/receipt.json')
published_files = {(x['sha256'], x['path']) for x in receipt['files']}
needed = [EX / 'protocols/design.json', EX / 'src/analyze_fixed.py',
          EX / 'others/model_inputs.csv', EX / 'others/fixed_analysis/predictions.csv']
slot_paths = sorted((ROOT / EX / 'others/fixed_analysis/fit_slots').glob('*_OPTION_O[01]_*.json'))
assert len(slot_paths) == 8
needed += [p.relative_to(ROOT) for p in slot_paths]
verified = []
for path in needed:
    ref = result['evidence'][path.as_posix()]
    assert ref['type'] == 'EvidenceRef'
    assert ref['experiment']['experiment_id'] == 'EX039_20261019'
    actual = digest(ROOT / path)
    assert actual == ref['sha256'], path
    # Delivery lists the published evidence payload by content identity.
    matches = [p for sha, p in published_files if sha == actual]
    assert matches, ('missing delivery content hash', path)
    verified.append({'path': path.as_posix(), 'sha256': actual,
                     'evidence_ref': ref, 'delivery_paths': matches})

with (ROOT / EX / 'others/model_inputs.csv').open(encoding='utf-8', newline='') as f:
    inputs = {int(row['signal']): row for row in csv.DictReader(f)}
with (ROOT / EX / 'others/fixed_analysis/predictions.csv').open(encoding='utf-8', newline='') as f:
    pred = {(int(row['year']), row['model'], int(row['signal'])): row
            for row in csv.DictReader(f) if row['family'] == 'OPTION'}
slots = {(r['year'], r['model']): r for r in map(read_json, slot_paths)}
rows = []
checks = {'score_error': D(0), 'score_difference_identity_error': D(0),
          'margin_identity_error': D(0), 'mse_allocation_identity_error': D(0),
          'fit_receipt_score_error': D(0), 'direct_raw_center_identity_error': D(0)}
folds = []
for year in (2023, 2024, 2025, 2026):
    r0, r1 = slots[year, 'O0'], slots[year, 'O1']
    assert r0['status'] == r1['status'] == 'SUCCESS'
    assert r0['train_signals'] == r1['train_signals']
    assert r0['test_signals'] == r1['test_signals']
    assert r1['columns'] == r0['columns'] + ['opt_delta_put']
    folds.append({'year': year, 'train_n': r0['train_n'], 'test_n': r0['test_n'],
                  'old_column_count': len(r0['columns']),
                  'new_standardized_coefficient': r1['standardized_coefficients'][-1],
                  'new_mean': r1['means'][-1], 'new_scale': r1['scales'][-1],
                  'threshold0': r0['threshold_q75'], 'threshold1': r1['threshold_q75'],
                  'threshold_delta': r1['threshold_q75'] - r0['threshold_q75'],
                  'intercept_delta': r1['intercept'] - r0['intercept'],
                  'old_means_identical': r0['means'] == r1['means'][:-1],
                  'old_scales_identical': r0['scales'] == r1['scales'][:-1]})
    for index, signal in enumerate(r0['test_signals']):
        data = inputs[signal]
        p0, p1 = pred[year, 'O0', signal], pred[year, 'O1', signal]
        assert p0['date'] == p1['date']
        assert datetime.fromisoformat(p0['date']).date() == datetime.fromisoformat(data['date']).date()
        terms = []
        for fit in (r0, r1):
            terms.append([(D(data[c]) - mu) / scale * beta
                          for c, mu, scale, beta in zip(
                              fit['columns'], fit['means'], fit['scales'],
                              fit['standardized_coefficients'])])
        s0, s1 = (D(p0['score']), D(p1['score']))
        for fit, pieces, saved in zip((r0, r1), terms, (s0, s1)):
            checks['score_error'] = max(checks['score_error'],
                                        abs(fit['intercept'] + sum(pieces) - saved))
            checks['fit_receipt_score_error'] = max(checks['fit_receipt_score_error'],
                                                    abs(fit['scores'][index] - saved))
        direct = terms[1][-1]
        beta, scale, mu = (r1['standardized_coefficients'][-1],
                           r1['scales'][-1], r1['means'][-1])
        raw = D(data['opt_delta_put']) / scale * beta
        centering = -mu / scale * beta
        old_shift = r1['intercept'] - r0['intercept'] + sum(terms[1][:-1]) - sum(terms[0])
        dt = r1['threshold_q75'] - r0['threshold_q75']
        m0, m1 = s0 - r0['threshold_q75'], s1 - r1['threshold_q75']
        keep0, keep1 = p0['keep'] == 'True', p1['keep'] == 'True'
        assert keep0 == r0['keep'][index] == (m0 < 0)
        assert keep1 == r1['keep'][index] == (m1 < 0)
        y, loss = D(p0['Y3']), D(p0['L'])
        assert y == D(p1['Y3']) and loss == D(p1['L'])
        assert loss == max(-y, D(0))
        mse = (loss - s0) ** 2 - (loss - s1) ** 2
        factor = 2 * loss - s0 - s1
        checks['score_difference_identity_error'] = max(
            checks['score_difference_identity_error'], abs(s1 - s0 - direct - old_shift))
        checks['margin_identity_error'] = max(
            checks['margin_identity_error'], abs(m1 - m0 - raw - centering - old_shift + dt))
        checks['mse_allocation_identity_error'] = max(
            checks['mse_allocation_identity_error'], abs(mse - factor * direct - factor * old_shift))
        checks['direct_raw_center_identity_error'] = max(
            checks['direct_raw_center_identity_error'], abs(direct - raw - centering))
        rows.append({'year': year, 'signal': signal, 'date': data['date'], 'Y3': y,
                     'L': loss, 'score0': s0, 'score1': s1, 'score_delta': s1-s0,
                     'direct_centered_option_term': direct,
                     'direct_raw_option_term': raw, 'option_mean_centering_term': centering,
                     'old_baseline_control_reallocation': old_shift,
                     'threshold_delta': dt, 'negative_threshold_delta_margin_term': -dt,
                     'margin0': m0, 'margin1': m1, 'margin_delta': m1-m0,
                     'keep0': keep0, 'keep1': keep1, 'changed': keep0 != keep1,
                     'allocation_difference': y * (int(keep1) - int(keep0)),
                     'mse_improvement': mse,
                     'symmetric_mse_allocation_direct': factor * direct,
                     'symmetric_mse_allocation_old': factor * old_shift})

assert len(rows) == 148 and sum(row['changed'] for row in rows) == 11
assert all(value < TOL for value in checks.values()), checks


def summarize(subset):
    changed = [r for r in subset if r['changed']]
    out = {'n': len(subset), 'changed_n': len(changed),
           'removed_n': sum(r['keep0'] and not r['keep1'] for r in subset),
           'added_n': sum(not r['keep0'] and r['keep1'] for r in subset)}
    fields = ('score_delta', 'direct_centered_option_term', 'direct_raw_option_term',
              'option_mean_centering_term', 'old_baseline_control_reallocation',
              'threshold_delta', 'margin_delta', 'allocation_difference',
              'mse_improvement', 'symmetric_mse_allocation_direct',
              'symmetric_mse_allocation_old')
    out['means'] = {field: mean(r[field] for r in subset) for field in fields}
    out['mean_absolute_terms'] = {field: mean(abs(r[field]) for r in subset)
                                  for field in fields[:7]}
    if changed:
        out['changed_rows_terms'] = {}
        for field in ('direct_centered_option_term', 'direct_raw_option_term',
                      'option_mean_centering_term', 'old_baseline_control_reallocation',
                      'negative_threshold_delta_margin_term'):
            out['changed_rows_terms'][field] = {
                'aligned_with_observed_margin_change': sum(r[field]*r['margin_delta'] > 0 for r in changed),
                'opposed_to_observed_margin_change': sum(r[field]*r['margin_delta'] < 0 for r in changed),
                'mean_absolute': mean(abs(r[field]) for r in changed)}
    return out


for name, selected in [('all_rows.csv', rows),
                        ('changed_rows.csv', [r for r in rows if r['changed']])]:
    with (OUT / name).open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(selected)
dump('source_hashes.json', {'status': 'PASS', 'verified_published_input_count': len(verified),
                          'verified': verified,
                          'anchors': [{'path': (EX / 'others/result.json').as_posix(),
                                       'sha256': digest(ROOT / EX / 'others/result.json')},
                                      {'path': 'research/S014/deliveries/COMPONENTS/22/receipt.json',
                                       'sha256': digest(ROOT / 'research/S014/deliveries/COMPONENTS/22/receipt.json')}],
                          'source': {'path': Path(__file__).relative_to(ROOT).as_posix(),
                                     'sha256': digest(Path(__file__))}})
results = {'status': 'PASS', 'scope': 'Existing saved OPTION O0/O1 only; no fit, label, rule, account, source call or causal ablation',
           'score_identity': 's1-s0 = centered_option_term + old_baseline_control_reallocation',
           'margin_convention': 'margin = saved_score - own_saved_threshold; keep iff margin < 0',
           'margin_identity': 'm1-m0 = raw_option_term + option_mean_centering_term + old_reallocation - threshold_delta',
           'old_reallocation_definition': 'Old columns contributions plus intercept difference; includes any mean/scale differences',
           'mse_identity': 'improvement = (2L-s0-s1)*(centered_option_term + old_reallocation)',
           'mse_allocation_warning': 'Symmetric algebraic allocation of cross terms; coordinate dependent, not causal or independent predictive value',
           'interpretation_warning': 'Centered option term, training centering offset and threshold movement jointly form saved model behavior. No term-alone scores or new keep rules are evaluated. Coefficients in both saved models were estimated jointly; feature addition can redistribute all old coefficients. Model intercept equals training mean loss, not a causal intercept.',
           'pure_arithmetic_checks_max_error': checks, 'folds': folds,
           'all': summarize(rows), 'without_2026': summarize([r for r in rows if r['year'] < 2026]),
           'years': {str(y): summarize([r for r in rows if r['year'] == y])
                                          for y in (2023, 2024, 2025, 2026)},
           'outputs': ['all_rows.csv', 'changed_rows.csv', 'source_hashes.json', 'decompose_saved_scores.py'],
           'new_fits': 0, 'new_labels': 0, 'new_rules': 0, 'new_accounts': 0, 'source_calls': 0}
dump('results.json', results)
print(json.dumps({'status': 'PASS', 'n': len(rows), 'changed': sum(r['changed'] for r in rows),
                  'all': results['all'], 'years': results['years'], 'checks': checks},
                 default=float, ensure_ascii=False))
