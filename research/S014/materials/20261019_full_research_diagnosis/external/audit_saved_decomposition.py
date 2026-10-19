"""Independent arithmetic audit; does not import the decomposition or any model code."""
import csv
import hashlib
import json
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 60
D = Decimal
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[4]
EX = ROOT / 'research/S014/experiments/EX039_20261019'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'), parse_float=D)


def table(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


result = load(EX / 'others/result.json')
inputs_path = EX / 'others/model_inputs.csv'
assert hashlib.sha256(inputs_path.read_bytes()).hexdigest() == result['evidence'][inputs_path.relative_to(ROOT).as_posix()]['sha256']
inputs = {int(r['signal']): r for r in table(inputs_path)}
rows = table(OUT / 'all_rows.csv')
changed = table(OUT / 'changed_rows.csv')
assert len(rows) == 148 and len(changed) == 11
assert {(r['year'], r['signal']) for r in changed} == {
    (r['year'], r['signal']) for r in rows if r['changed'] == 'True'}
fits = {}
for path in (EX / 'others/fixed_analysis/fit_slots').glob('*_OPTION_O[01]_*.json'):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == result['evidence'][path.relative_to(ROOT).as_posix()]['sha256']
    r = load(path)
    fits[r['year'], r['model']] = r
max_error = D(0)
checked = 0
for row in rows:
    year, signal = int(row['year']), int(row['signal'])
    x = inputs[signal]
    f0, f1 = fits[year, 'O0'], fits[year, 'O1']
    # Convert each stored model independently to raw slopes and its raw intercept.
    raw_models = []
    for f in (f0, f1):
        slopes = dict(zip(f['columns'], [b / s for b, s in zip(f['standardized_coefficients'], f['scales'])]))
        intercept = f['intercept'] - sum(slopes[c]*mu for c, mu in zip(f['columns'], f['means']))
        score = intercept + sum(slopes[c]*D(x[c]) for c in slopes)
        raw_models.append((slopes, intercept, score))
    b0, a0, s0 = raw_models[0]
    b1, a1, s1 = raw_models[1]
    direct_raw = b1['opt_delta_put']*D(x['opt_delta_put'])
    center = -b1['opt_delta_put']*f1['means'][-1]
    old = sum((b1[c]-b0[c])*D(x[c]) for c in b0) + a1-a0-center
    t_delta = f1['threshold_q75']-f0['threshold_q75']
    expectations = {'score0': s0, 'score1': s1, 'score_delta': s1-s0,
                    'direct_raw_option_term': direct_raw, 'option_mean_centering_term': center,
                    'direct_centered_option_term': direct_raw+center,
                    'old_baseline_control_reallocation': old,
                    'margin0': s0-f0['threshold_q75'], 'margin1': s1-f1['threshold_q75'],
                    'threshold_delta': t_delta, 'negative_threshold_delta_margin_term': -t_delta,
                    'margin_delta': direct_raw+center+old-t_delta}
    loss = D(row['L'])
    improvement = (loss-s0)**2-(loss-s1)**2
    expectations['mse_improvement'] = improvement
    expectations['symmetric_mse_allocation_direct'] = (2*loss-s0-s1)*(direct_raw+center)
    expectations['symmetric_mse_allocation_old'] = (2*loss-s0-s1)*old
    for key, expected in expectations.items():
        error = abs(D(row[key])-expected)
        assert error < D('1e-12'), (signal, key, error)
        max_error = max(max_error, error)
        checked += 1
    assert (D(row['margin0']) < 0) == (row['keep0'] == 'True')
    assert (D(row['margin1']) < 0) == (row['keep1'] == 'True')
    allocation = D(row['Y3'])*(int(row['keep1'] == 'True')-int(row['keep0'] == 'True'))
    assert allocation == D(row['allocation_difference'])

audit = {'status': 'PASS', 'method': 'Independent Decimal60 raw-slope/raw-intercept arithmetic; no producer import, fitting, labels or alternative decision rules',
         'rows': len(rows), 'changed_rows': len(changed), 'numeric_checks': checked,
         'max_absolute_error': float(max_error),
         'new_fits': 0, 'new_labels': 0, 'new_accounts': 0, 'source_calls': 0,
         'files': [{'path': p.relative_to(ROOT).as_posix(),
                    'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in [OUT/'decompose_saved_scores.py', Path(__file__), OUT/'all_rows.csv',
                             OUT/'changed_rows.csv', OUT/'results.json', OUT/'source_hashes.json']]}
(OUT / 'independent_arithmetic_audit.json').write_text(json.dumps(audit, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
print(json.dumps(audit, ensure_ascii=False))
