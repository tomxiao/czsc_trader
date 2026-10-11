"""Create EX082 fixed calendar component sources without reading market data."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / '.tmp/s013-confirm-context'
WORK = ROOT / '.tmp/s013-calendar-phase'
WORK.mkdir(exist_ok=True)

models = "('training_mean', 'confirmation_only', 'original14_joint', 'calendar_only', 'confirmation_calendar', 'original14_calendar')"
quantities = """('calendar_mse_improvement_vs_mean', 'confirmation_calendar_mse_improvement_vs_confirmation',
              'original14_calendar_mse_improvement_vs_original14', 'calendar_positive_mean',
              'confirmation_calendar_positive_mean', 'original14_calendar_positive_mean',
              'calendar_positive_mean_minus_all', 'confirmation_calendar_positive_mean_minus_confirmation',
              'original14_calendar_positive_mean_minus_original14', 'original14_calendar_mse_improvement_vs_mean')"""

def constants(text):
    start, end = text.index('MODELS = '), text.index('\n\n\ndef ', text.index('QUANTITIES = '))
    return text[:start] + 'MODELS = ' + models + '\nNEW_MODELS = MODELS[3:]\nQUANTITIES = ' + quantities + text[end:]

def section(text, name, following, body):
    start, end = text.index('def ' + name + '('), text.index('def ' + following + '(')
    return text[:start] + body.strip() + '\n\n\n' + text[end:]

k = constants((OLD / 'kernel.py').read_text('utf-8'))
k = k.replace('EX081 confirmation by signed price context', 'EX082 causal civil-month harmonic phase')
k = section(k, 'design', 'fit', '''
def calendar(axis):
    phase = (axis.day.to_numpy(float) - 1) / axis.days_in_month.to_numpy(float)
    return np.column_stack((.5 * np.sin(2 * np.pi * phase), .5 * np.cos(2 * np.pi * phase)))


def design(train_x, values, dates, model):
    time = calendar(dates)
    if model == 'calendar_only':
        return time
    positions = (8,) if model == 'confirmation_calendar' else range(14)
    ranked = np.column_stack([rank(train_x[:, j], values[:, j]) - .5 for j in positions])
    return np.column_stack((ranked, time))
''')
k = k.replace("    cf, mom = x[:, 8], x[:, 0]\n", '')
k = k.replace("               'train_state_counts': {str(int(s)): int((np.sign(mom[train]) == s).sum()) for s in (-1, 0, 1)},\n", '')
k = k.replace("            for model, interaction in zip(NEW_MODELS, (False, True)):\n                tx = design(cf[train], cf[train], mom[train], interaction)\n                vx = design(cf[train], cf[test], mom[test], interaction)",
"            for model in NEW_MODELS:\n                tx = design(x[train], x[train], axis[train], model)\n                vx = design(x[train], x[test], axis[test], model)")
k = section(k, 'quantities', 'bootstrap', '''
def quantities(y, prediction, indices):
    yy, pp = y[indices], prediction[indices]
    valid = np.isfinite(yy) & np.isfinite(pp).all(axis=1)
    yy, pp = yy[valid], pp[valid]
    means = [float(yy[pp[:, j] > 0].mean()) if int((pp[:, j] > 0).sum()) >= 20 else None for j in range(6)]
    mse = np.mean((yy[:, None] - pp) ** 2, axis=0) if len(yy) >= 20 else None
    result = {key: float(1 - mse[a] / mse[b]) if mse is not None and mse[b] > 0 else None
              for key, (a, b) in zip(QUANTITIES[:3], ((3, 0), (4, 1), (5, 2)))}
    result.update(dict(zip(QUANTITIES[3:6], means[3:])))
    result[QUANTITIES[6]] = means[3] - float(yy.mean()) if means[3] is not None and len(yy) >= 20 else None
    for key, new, old in ((QUANTITIES[7], 4, 1), (QUANTITIES[8], 5, 2)):
        result[key] = means[new] - means[old] if means[new] is not None and means[old] is not None else None
    result[QUANTITIES[9]] = float(1 - mse[5] / mse[0]) if mse is not None and mse[0] > 0 else None
    return result
''')
k = k.replace("             **{'phase_' + str(k):", "             **{'civil_quarter_' + str(q): np.floor(4 * (axis.day.to_numpy() - 1) / axis.days_in_month.to_numpy()) == q for q in range(4)},\n             **{'phase_' + str(k):")
k = k.replace("'new_annual_models': 2 * len(years)", "'new_annual_models': 3 * len(years)")
(WORK / 'kernel.py').write_text(k, encoding='utf-8', newline='\n')

a = constants((OLD / 'audit.py').read_text('utf-8'))
a = a.replace('from math import fsum, exp, log1p', 'from math import fsum, exp, log1p, sin, cos, pi\nfrom calendar import monthrange')
a = section(a, 'forecasts', 'compare', '''
def calendar(dates):
    return [[.5 * sin(2 * pi * (d.day - 1) / monthrange(d.year, d.month)[1]),
             .5 * cos(2 * pi * (d.day - 1) / monthrange(d.year, d.month)[1])] for d in dates]


def forecasts(features, labels, prior):
    axis, x = features.index, features.to_numpy(float)
    complete = [all(np.isfinite(v) for v in r) for r in x]
    target = labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    result = prior.copy()
    for name in MODELS[3:]:
        result[name] = np.nan
    fits = {}
    for year in sorted(set(day.year for day in axis if day.year >= 2021)):
        first = next(day for day in axis if day.year == year)
        tr = [i for i, t in enumerate(axis) if complete[i] and np.isfinite(target[i]) and 2020 <= t.year < year and ends.iloc[i] < first]
        te = [i for i, t in enumerate(axis) if complete[i] and t.year == year]
        row = {'first_signal': first.isoformat(), 'train_n': len(tr), 'feature_test_n': len(te),
               'max_maturity': max(ends.iloc[i] for i in tr).isoformat() if tr else None,
               'train_dates': [axis[i].isoformat() for i in tr], 'future_test_count_gate': False, 'coefficients': {}}
        if len(tr) >= 40:
            rt = [cdf(x[tr, j], x[tr, j]) for j in range(14)]
            rv = [cdf(x[tr, j], x[te, j]) for j in range(14)]
            ct, cv = calendar(axis[tr]), calendar(axis[te])
            for name, columns in zip(MODELS[3:], ((), (8,), tuple(range(14)))):
                tx = [[rt[j][i] - .5 for j in columns] + ct[i] for i in range(len(tr))]
                vx = [[rv[j][i] - .5 for j in columns] + cv[i] for i in range(len(te))]
                prediction, coef = ridge(tx, target[tr], vx)
                result.iloc[te, result.columns.get_loc(name)] = prediction
                row['coefficients'][name] = coef
        fits[str(year)] = row
    return result, fits
''')
a = section(a, 'quantities', 'verify', '''
def quantities(target, scores, ids):
    ix = [int(i) for i in ids if np.isfinite(target[i]) and all(np.isfinite(v) for v in scores[i])]
    errors = [mean([(float(target[i]) - float(scores[i, j])) ** 2 for i in ix]) for j in range(6)] if len(ix) >= 20 else None
    avg = [mean([target[i] for i in ix if scores[i, j] > 0]) if sum(scores[i, j] > 0 for i in ix) >= 20 else None for j in range(6)]
    out = {key: float(1 - errors[a] / errors[b]) if errors is not None and errors[b] > 0 else None
           for key, (a, b) in zip(QUANTITIES[:3], ((3, 0), (4, 1), (5, 2)))}
    out.update(dict(zip(QUANTITIES[3:6], avg[3:])))
    out[QUANTITIES[6]] = avg[3] - mean([target[i] for i in ix]) if avg[3] is not None and len(ix) >= 20 else None
    for key, new, old in ((QUANTITIES[7], 4, 1), (QUANTITIES[8], 5, 2)):
        out[key] = avg[new] - avg[old] if avg[new] is not None and avg[old] is not None else None
    out[QUANTITIES[9]] = float(1 - errors[5] / errors[0]) if errors is not None and errors[0] > 0 else None
    return out
''')
a = a.replace("             **{'phase_' + str(k):", "             **{'civil_quarter_' + str(q): [i for i, x in enumerate(axis) if 4 * (x.day - 1) // monthrange(x.year, x.month)[1] == q] for q in range(4)},\n             **{'phase_' + str(k):")
a = a.replace("'annual_models': 2 * len(fits)", "'annual_models': 3 * len(fits)")
(WORK / 'audit.py').write_text(a, encoding='utf-8', newline='\n')

s = (OLD / 'focused_checks.py').read_text('utf-8').replace('EX081', 'EX082')
s = s.replace("truth = .002 * cf + .001 * state + .025 * cf * state + rng.normal(0, .003, 400)",
"time = kernel.calendar(axis)\ntruth = .002 * cf + .010 * time[:, 0] - .007 * time[:, 1] + rng.normal(0, .003, 400)")
start, end = s.index('same_cf = '), s.index('scores, result = ')
s = s[:start] + '''dates = pd.DatetimeIndex(['2020-02-29', '2021-02-28', '2020-04-01', '2020-04-16'])
np.testing.assert_allclose(kernel.calendar(dates), audit.calendar(dates), atol=2e-15)
np.testing.assert_allclose(kernel.calendar(dates)[2:], [[0., .5], [0., -.5]], atol=2e-15)
np.testing.assert_allclose(kernel.calendar(axis[:1]), kernel.calendar(axis)[:1], atol=0)
assert np.all(np.abs(kernel.calendar(axis)) <= .5)
''' + s[end:]
s = s.replace('Context interaction reverses with signed momentum', 'Known civil date phase incl leap years and prefix independent of future trading calendar')
(WORK / 'focused_checks.py').write_text(s, encoding='utf-8', newline='\n')

d = (ROOT / '.tmp/s013_context_driver.py').read_text('utf-8').replace('EX081', 'EX082').replace('Slot3', 'Slot4')
d = d.replace('s013-confirm-context-result', 's013-calendar-phase-result').replace('s013-confirm-context', 's013-calendar-phase')
d = d.replace("raw_y = prices.Open.shift(-5) / prices.Open.shift(-1)", "raw_y = prices['open'].shift(-5) / prices['open'].shift(-1)")
d = d.replace("ExperimentRequest('确认信息与涨跌状态的最小机制对照', '控制原确认分数与20日涨跌方向后，单一交互项是否增加固定四日净机会识别能力？'", "ExperimentRequest('已知自然日期的月内周期信息对照', '月内平滑时间位置能否补充原确认与14项价量信号的四日扣费后机会识别？'")
d = d.replace("'slot': 3", "'slot': 4")
(ROOT / '.tmp/s013_calendar_driver.py').write_text(d, encoding='utf-8', newline='\n')
print('Calendar sources written; no real data read, models fitted or experiment allocated')
