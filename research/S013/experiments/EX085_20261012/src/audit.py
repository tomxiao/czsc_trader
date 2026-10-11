"""Scalar mature-window, matched ridge/Newton and economic utility audit."""
from bisect import bisect_left, bisect_right
from math import fsum, exp, log, log1p
import numpy as np
import pandas as pd

MODELS = ('training_mean', 'original14_return', 'original14_state_return', 'original14_probability_payoff', 'original14_state_probability_payoff')
PROBABILITIES = ('training_probability', 'original14_probability', 'original14_state_probability')
QUANTITIES = ('state_brier_improvement_vs_original14', 'state_logloss_improvement_vs_original14',
              'state_return_mse_improvement_vs_original14', 'state_payoff_mse_improvement_vs_original14_payoff',
              'state_return_positive_mean', 'state_payoff_positive_mean',
              'state_return_mean_minus_original14', 'state_payoff_mean_minus_original14_payoff',
              'state_brier_improvement_vs_prior', 'state_logloss_improvement_vs_prior')


def mean(values):
    return fsum(float(v) for v in values) / len(values)


def cdf(train, values):
    ordered = sorted(float(v) for v in train)
    return [(bisect_left(ordered, float(v)) + bisect_right(ordered, float(v))) / (2 * len(ordered)) - .5 for v in values]


def solve(matrix, right):
    n = len(right)
    a = [[float(v) for v in row] + [float(right[i])] for i, row in enumerate(matrix)]
    for i in range(n):
        best = max(range(i, n), key=lambda j: abs(a[j][i]))
        a[i], a[best] = a[best], a[i]
        if abs(a[i][i]) < 1e-14:
            raise ValueError('Independent Newton system singular')
        pivot = a[i][i]
        a[i] = [v / pivot for v in a[i]]
        for j in range(n):
            if j != i:
                factor = a[j][i]
                a[j] = [u - factor * v for u, v in zip(a[j], a[i])]
    return [a[i][-1] for i in range(n)]


def sigmoid(z):
    return 1 / (1 + exp(-z)) if z >= 0 else exp(z) / (1 + exp(z))


def softplus(z):
    return z + log1p(exp(-z)) if z >= 0 else log1p(exp(z))


def fit(train, binary, test):
    x = [[1., *map(float, row)] for row in train]
    n, d = len(x), len(x[0])
    fraction = mean(binary)
    if not 0 < fraction < 1:
        raise ValueError('Both classes required')
    beta = [log(fraction / (1 - fraction)), *([0.] * (d - 1))]
    penalty = [0., *([10.] * (d - 1))]
    def objective(b):
        z = [fsum(a * v for a, v in zip(row, b)) for row in x]
        return fsum(softplus(v) - float(t) * v for v, t in zip(z, binary)) + .5 * fsum(k * v * v for k, v in zip(penalty, b))
    for iteration in range(100):
        p = [sigmoid(fsum(a * b for a, b in zip(row, beta))) for row in x]
        g = [fsum(x[i][j] * (p[i] - float(binary[i])) for i in range(n)) + penalty[j] * beta[j] for j in range(d)]
        norm = max(abs(v) for v in g)
        if norm <= 1e-10:
            result = [sigmoid(fsum(a * b for a, b in zip([1., *row], beta))) for row in test]
            return result, {'coefficients': beta, 'iterations': iteration, 'max_abs_gradient': norm, 'objective': objective(beta)}
        h = [[fsum(x[i][a] * x[i][b] * p[i] * (1 - p[i]) for i in range(n)) + (penalty[a] if a == b else 0.) for b in range(d)] for a in range(d)]
        step = solve(h, g)
        rate, old = 1., objective(beta)
        for _ in range(40):
            candidate = [v - rate * s for v, s in zip(beta, step)]
            if objective(candidate) <= old - 1e-4 * rate * fsum(a * b for a, b in zip(g, step)) + 1e-12:
                beta = candidate
                break
            rate *= .5
        else:
            raise ValueError('Independent line search failed')
    raise ValueError('Independent logistic convergence failed')


def ridge(train, target, test):
    n, d = len(train), len(train[0])
    mx, my = [mean([r[j] for r in train]) for j in range(d)], mean(target)
    z = [[r[j]-mx[j] for j in range(d)] for r in train]
    matrix = [[fsum(z[i][a]*z[i][b] for i in range(n))+(10 if a==b else 0) for b in range(d)] for a in range(d)]
    right = [fsum(z[i][j]*(float(target[i])-my) for i in range(n)) for j in range(d)]
    slopes = solve(matrix,right)
    intercept = my-fsum(a*b for a,b in zip(mx,slopes))
    return [intercept+fsum(a*b for a,b in zip(row,slopes)) for row in test],[intercept,*slopes]


def states(axis,y,ends):
    rows,traces=[],[]
    for date in axis:
        eligible=[i for i in range(len(axis)) if np.isfinite(y[i]) and pd.notna(ends.iloc[i]) and ends.iloc[i]<=date]
        window=eligible[-20:] if len(eligible)>=20 else []
        rows.append([sum(y[i]>0 for i in window)/20,mean(y[window])] if window else [np.nan,np.nan])
        traces.append({'signal_date':date.isoformat(),'eligible_mature':len(eligible),'available':len(window)==20,
                       'positions':window,'max_maturity':max(ends.iloc[i] for i in window).isoformat() if window else None})
    return pd.DataFrame(rows,index=axis,columns=('mature_h4_win_fraction20','mature_h4_mean_net20')),traces


def forecasts(features,labels):
    axis,y=features.index,labels.return_4.to_numpy(float)
    ends=pd.to_datetime(labels.label_end_return_4)
    state,traces=states(axis,y,ends)
    x=np.column_stack((features.to_numpy(float),state.to_numpy(float)))
    complete=[all(np.isfinite(v) for v in row) for row in x]
    nets=pd.DataFrame(np.nan,index=axis,columns=MODELS)
    probs=pd.DataFrame(np.nan,index=axis,columns=PROBABILITIES)
    years={}
    for year in sorted(set(t.year for t in axis if t.year>=2021)):
        first=next(t for t in axis if t.year==year)
        tr=[i for i,t in enumerate(axis) if complete[i] and np.isfinite(y[i]) and 2020<=t.year<year and ends.iloc[i]<first]
        te=[i for i,t in enumerate(axis) if complete[i] and t.year==year]
        wins=[i for i in tr if y[i]>0]
        losses=[i for i in tr if y[i]<=0]
        available=len(tr)>=40 and len(wins)>=20 and len(losses)>=20
        row={'first_signal':first.isoformat(),'train_n':len(tr),'win_n':len(wins),'nonpositive_n':len(losses),
             'max_maturity':max(ends.iloc[i] for i in tr).isoformat() if tr else None,'train_dates':[axis[i].isoformat() for i in tr],
             'feature_test_n':len(te),'available':available,'future_test_count_gate':False,'payoffs':None,
             'return_models':{},'probability_models':{}}
        if available:
            fraction,gain,negative=len(wins)/len(tr),mean(y[wins]),mean(y[losses])
            row['payoffs']={'win_fraction':fraction,'mean_positive':gain,'mean_nonpositive':negative,
                            'break_even_probability':-negative/(gain-negative),'unconditional_net_mean':mean(y[tr])}
            nets.iloc[te,0]=mean(y[tr])
            probs.iloc[te,0]=fraction
            rt=[cdf(x[tr,j],x[tr,j]) for j in range(16)]
            rv=[cdf(x[tr,j],x[te,j]) for j in range(16)]
            for dim,net_name,prob_name,payoff_name in ((14,MODELS[1],PROBABILITIES[1],MODELS[3]),(16,MODELS[2],PROBABILITIES[2],MODELS[4])):
                tx=[[r[i] for r in rt[:dim]] for i in range(len(tr))]
                vx=[[r[i] for r in rv[:dim]] for i in range(len(te))]
                prediction,coef=ridge(tx,y[tr],vx)
                p,proof=fit(tx,[int(y[i]>0) for i in tr],vx)
                nets.iloc[te,nets.columns.get_loc(net_name)]=prediction
                probs.iloc[te,probs.columns.get_loc(prob_name)]=p
                nets.iloc[te,nets.columns.get_loc(payoff_name)]=[v*gain+(1-v)*negative for v in p]
                row['return_models'][net_name]=coef
                row['probability_models'][prob_name]=proof
        years[str(year)]=row
    return state,traces,probs,nets,years


def compare(a, b, where='root'):
    if isinstance(b, dict):
        assert set(a) == set(b), where
        for key in b:
            compare(a[key], b[key], where + '/' + key)
    elif isinstance(b, list):
        assert len(a) == len(b), where
        for i, (aa, bb) in enumerate(zip(a, b)):
            compare(aa, bb, where + '/' + str(i))
    elif isinstance(b, float):
        assert np.isclose(a, b, atol=3e-12, rtol=2e-9), (where, a, b)
    else:
        assert a == b, (where, a, b)


def group(y, prediction, ids):
    eligible = [i for i in ids if np.isfinite(prediction[i])]
    positive = [i for i in eligible if prediction[i] > 0]
    mature = [i for i in positive if np.isfinite(y[i])]
    n = len(mature)
    return {'forecasts': len(eligible), 'positive_forecasts': len(positive), 'mature_positive': n,
            'missing_positive_truth': len(positive) - n, 'positive_mean': mean(y[mature]) if n >= 20 else None,
            'hit_rate': sum(y[i] > 0 for i in mature) / n if n >= 20 else None,
            'false_positive_rate': sum(y[i] <= 0 for i in mature) / n if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def quantities(y,p,nets,ids):
    ix=[int(i) for i in ids if np.isfinite(y[int(i)]) and np.isfinite(p[int(i)]).all() and np.isfinite(nets[int(i)]).all()]
    if len(ix)<20:
        return dict.fromkeys(QUANTITIES)
    binary=[int(y[i]>0) for i in ix]
    brier=[mean([(p[i,j]-b)**2 for i,b in zip(ix,binary)]) for j in range(3)]
    losses=[mean([-b*log(p[i,j])-(1-b)*log1p(-p[i,j]) for i,b in zip(ix,binary)]) for j in range(3)]
    mse=[mean([(nets[i,j]-y[i])**2 for i in ix]) for j in range(5)]
    avg=[]
    for j in range(5):
        v=[y[i] for i in ix if nets[i,j]>0]
        avg.append(mean(v) if len(v)>=20 else None)
    out={key:float(1-values[a]/values[b]) if values[b]>0 else None for key,(values,a,b) in zip(QUANTITIES[:4],((brier,2,1),(losses,2,1),(mse,2,1),(mse,4,3)))}
    out.update({QUANTITIES[4]:avg[2],QUANTITIES[5]:avg[4]})
    for key,new,old in ((QUANTITIES[6],2,1),(QUANTITIES[7],4,3)):
        out[key]=avg[new]-avg[old] if avg[new] is not None and avg[old] is not None else None
    out[QUANTITIES[8]]=float(1-brier[2]/brier[0]) if brier[0]>0 else None
    out[QUANTITIES[9]]=float(1-losses[2]/losses[0]) if losses[0]>0 else None
    return out


def verify(features, labels, reported_states, reported_probs, reported_nets, report, clock):
    state, traces, probs, nets, fits = forecasts(features, labels)
    np.testing.assert_allclose(reported_states,state,atol=3e-12,rtol=2e-9,equal_nan=True)
    compare(report['state_traces'],traces,'state_traces')
    np.testing.assert_allclose(reported_probs, probs, atol=3e-12, rtol=2e-9, equal_nan=True)
    np.testing.assert_allclose(reported_nets, nets, atol=3e-12, rtol=2e-9, equal_nan=True)
    np.testing.assert_array_equal(reported_nets.to_numpy() > 0, nets.to_numpy() > 0)
    compare(report['fit_years'], fits, 'fits')
    axis, y, p, n = features.index, labels.return_4.to_numpy(float), probs.to_numpy(float), nets.to_numpy(float)
    common = [i for i in range(len(y)) if np.isfinite(y[i]) and np.isfinite(p[i]).all() and np.isfinite(n[i]).all()]
    assert report['mature_common'] == len(common)
    masks = {'all': list(range(len(y))), **{'year_' + str(t): [i for i, d in enumerate(axis) if d.year == t] for t in range(2020, 2027)},
             **{'phase_' + str(k): [i for i in range(len(y)) if i % 5 == k] for k in range(5)}}
    panels = {key: {m: group(y, n[:, j], ids) for j, m in enumerate(MODELS)} for key, ids in masks.items()}
    compare(report['panels'], panels, 'panels')
    probability_quality = {}
    for key, ids in masks.items():
        ix = [i for i in ids if i in common]
        binary = [int(y[i] > 0) for i in ix]
        probability_quality[key] = {}
        for j, m in enumerate(PROBABILITIES):
            probability_quality[key][m] = {'n': len(ix), 'brier': mean([(p[i, j] - b) ** 2 for i, b in zip(ix, binary)]) if len(ix) >= 20 else None,
                'logloss': mean([-b * log(p[i, j]) - (1 - b) * log1p(-p[i, j]) for i, b in zip(ix, binary)]) if len(ix) >= 20 else None,
                'mean_probability': mean([p[i, j] for i in ix]) if len(ix) >= 20 else None,
                'observed_positive_fraction': mean(binary) if len(ix) >= 20 else None}
    compare(report['probability_quality'], probability_quality, 'probability_quality')
    schedules = {}
    for j, model in enumerate(MODELS):
        prediction = n[:, j]
        positive = [i for i, v in enumerate(prediction) if np.isfinite(v) and v > 0]
        schedules[model] = {}
        for name in clock.CLOCKS:
            ix = clock.selected(prediction, name)
            mature = [i for i in ix if np.isfinite(y[i])]
            accepted = set(ix)
            blocked = [i for i in positive if i not in accepted]
            mb = [i for i in blocked if np.isfinite(y[i])]
            panel = {'all': clock.attribution(y, ix), **{'year_' + str(t): clock.attribution(y, [i for i in ix if axis[i].year == t]) for t in range(2020, 2027)}}
            schedules[model][name] = {'accepted': len(ix), 'missing_truth_accepted': len(ix) - len(mature),
                'positive_forecasts': len(positive), 'blocked_positive_forecasts': len(blocked),
                'accepted_mean': mean(y[mature]) if len(mature) >= 20 else None,
                'blocked_positive_mean': mean(y[mb]) if len(mb) >= 20 else None, 'mature_blocked_positive': len(mb), 'panels': panel,
                'records': [{'signal_date': axis[i].isoformat(), 'position': i, 'prediction': float(prediction[i]),
                             'proxy_return': float(y[i]) if np.isfinite(y[i]) else None} for i in ix]}
    compare(report['schedules'], schedules, 'schedules')
    rng = np.random.default_rng(13)
    starts = rng.integers(0, len(y) - 39, (500, (len(y) + 39) // 40))
    ids = np.concatenate([starts[:, j:j + 1] + np.arange(40) for j in range(starts.shape[1])], axis=1)[:, :len(y)]
    records = [quantities(y, p, n, row) for row in ids]
    compare(report['bootstrap']['records'], records, 'bootstrap_records')
    original = quantities(y, p, n, list(range(len(y))))
    summary = {}
    for name, value in original.items():
        good = [r[name] for r in records if r[name] is not None]
        ok = value is not None and len(good) >= 400
        summary[name] = {'value': value, 'valid_replicates': len(good), 'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                         'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'], summary, 'bootstrap_summary')
    return {'status': 'PASS', 'new_annual_models': 4 * sum(r['available'] for r in fits.values()),
            'new_accounts': 0, 'forecast_rows': len(y), 'mature_common': len(common), 'positive_flags': 'EXACT',
            'scalar_logistic_normal_equations': True, 'payoff_decomposition': 'VERIFIED', 'state_cells': 2*len(y), 'matched_training': True,
            'schedules': 30, 'bootstrap_checks': 5000, 'probability_and_net_forecasts': 'VERIFIED'}
