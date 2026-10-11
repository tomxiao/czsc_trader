"""Independent scalar state machine and log-based EX083 attribution audit."""
from math import fsum, log1p, exp, ceil
import numpy as np

MODELS = ('training_mean', 'confirmation_only', 'original14_joint', 'calendar_only', 'confirmation_calendar', 'original14_calendar')
CLOCKS = ('greedy', 'phase_0', 'phase_1', 'phase_2', 'phase_3', 'phase_4')
QUANTITIES = ('calendar_greedy_mean', 'calendar_greedy_minus_confirmation_greedy',
              'calendar_greedy_minus_blocked_positive', 'calendar_phase_0_mean', 'calendar_phase_1_mean',
              'calendar_phase_2_mean', 'calendar_phase_3_mean', 'calendar_phase_4_mean', 'calendar_worst_phase_mean')


def mean(values):
    return fsum(float(v) for v in values) / len(values)


def selected(p, clock):
    out, busy = [], 0
    for i, value in enumerate(p):
        if clock == 'greedy':
            if busy:
                busy -= 1
            elif np.isfinite(value) and value > 0:
                out.append(i)
                busy = 4
        elif i % 5 == int(clock[-1]) and np.isfinite(value) and value > 0:
            out.append(i)
    return out


def compound(values):
    return exp(fsum(log1p(float(v)) for v in values)) - 1 if values else None


def attribution(y, ids):
    ix = [i for i in ids if np.isfinite(y[i])]
    winners = sorted([i for i in ix if y[i] > 0], key=lambda i: (-float(y[i]), i))
    top = winners[:ceil(.1 * len(winners))]
    best = winners[:1]
    positive_sum = fsum(float(y[i]) for i in winners)
    return {'mature': len(ix), 'mean_net_proxy': mean([y[i] for i in ix]) if len(ix) >= 20 else None,
            'mean_status': 'AVAILABLE' if len(ix) >= 20 else 'INSUFFICIENT_DATA',
            'compound_net_proxy': compound([y[i] for i in ix]), 'positive_count': len(winners),
            'top_positive_count': len(top), 'top_positive_contribution': fsum(float(y[i]) for i in top) / positive_sum if positive_sum > 0 else None,
            'best_positive_contribution': fsum(float(y[i]) for i in best) / positive_sum if positive_sum > 0 else None,
            'compound_without_best_positive': compound([y[i] for i in ix if i not in best]) if best else None,
            'compound_without_top10pct_positive': compound([y[i] for i in ix if i not in top]) if top else None,
            'best_positive_positions': best, 'top_positive_positions': top,
            'actual_closed_trades': None, 'continuous_account_return': None}


def compare(a, b, where='root'):
    if isinstance(b, dict):
        assert set(a) == set(b), where
        for k in b:
            compare(a[k], b[k], where + '/' + k)
    elif isinstance(b, list):
        assert len(a) == len(b), where
        for i, (aa, bb) in enumerate(zip(a, b)):
            compare(aa, bb, where + '/' + str(i))
    elif isinstance(b, float):
        assert np.isclose(a, b, atol=3e-12, rtol=2e-9), (where, a, b)
    else:
        assert a == b, (where, a, b)


def schedules(scores, labels):
    y, axis = labels.return_4.to_numpy(float), scores.index
    output = {}
    for model in MODELS:
        p = scores[model].to_numpy(float)
        positive = [i for i, v in enumerate(p) if np.isfinite(v) and v > 0]
        output[model] = {}
        for clock in CLOCKS:
            ids = selected(p, clock)
            accepted = set(ids)
            blocked = [i for i in positive if i not in accepted]
            mature_blocked = [i for i in blocked if np.isfinite(y[i])]
            mature = [i for i in ids if np.isfinite(y[i])]
            panels = {'all': attribution(y, ids), **{'year_' + str(t): attribution(y, [i for i in ids if axis[i].year == t]) for t in range(2020, 2027)}}
            output[model][clock] = {'accepted': len(ids), 'missing_truth_accepted': len(ids) - len(mature),
                'positive_forecasts': len(positive), 'blocked_positive_forecasts': len(blocked),
                'accepted_mean': mean([y[i] for i in mature]) if len(mature) >= 20 else None,
                'blocked_positive_mean': mean([y[i] for i in mature_blocked]) if len(mature_blocked) >= 20 else None,
                'mature_blocked_positive': len(mature_blocked), 'panels': panels,
                'records': [{'signal_date': axis[i].isoformat(), 'position': i, 'prediction': float(p[i]),
                             'proxy_return': float(y[i]) if np.isfinite(y[i]) else None} for i in ids]}
    return output


def quantities(y, selections, ids):
    avg = {}
    for name, accepted in selections.items():
        values = [y[int(i)] for i in ids if int(i) in accepted and np.isfinite(y[int(i)])]
        avg[name] = mean(values) if len(values) >= 20 else None
    output = {QUANTITIES[0]: avg['greedy']}
    for key, other in ((QUANTITIES[1], 'confirmation_greedy'), (QUANTITIES[2], 'blocked_positive')):
        output[key] = avg['greedy'] - avg[other] if avg['greedy'] is not None and avg[other] is not None else None
    for phase in range(5):
        output[QUANTITIES[3 + phase]] = avg['phase_' + str(phase)]
    phases = [avg['phase_' + str(k)] for k in range(5)]
    output[QUANTITIES[-1]] = min(phases) if all(v is not None for v in phases) else None
    return output


def verify(scores, labels, report):
    expected = schedules(scores, labels)
    compare(report['schedules'], expected, 'schedules')
    y, p = labels.return_4.to_numpy(float), scores.to_numpy(float)
    n = len(y)
    selections = {clock: set(selected(p[:, 3], clock)) for clock in CLOCKS}
    selections['confirmation_greedy'] = set(selected(p[:, 1], 'greedy'))
    selections['blocked_positive'] = {i for i, v in enumerate(p[:, 3]) if np.isfinite(v) and v > 0 and i not in selections['greedy']}
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 39, (500, ceil(n / 40)))
    samples = np.concatenate([starts[:, j:j + 1] + np.arange(40) for j in range(starts.shape[1])], axis=1)[:, :n]
    records = [quantities(y, selections, ids) for ids in samples]
    compare(report['bootstrap']['records'], records, 'bootstrap_records')
    original = quantities(y, selections, list(range(n)))
    summary = {}
    for name, value in original.items():
        good = [r[name] for r in records if r[name] is not None]
        ok = value is not None and len(good) >= 400
        summary[name] = {'value': value, 'valid_replicates': len(good),
                         'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                         'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'], summary, 'bootstrap_summary')
    return {'status': 'PASS', 'forecast_rows': n, 'schedules': 36, 'year_panels': 36 * 8,
            'profit_concentration_and_omissions': 'ALL_SCALAR_LOG_PRODUCTS_VERIFIED',
            'bootstrap_replicates': 500, 'bootstrap_quantities': 9, 'bootstrap_records_checked': 4500,
            'entry_positions': 'EXACT', 'new_accounts': 0, 'new_models': 0}
