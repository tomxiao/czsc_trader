"""Independent price-segment and retained statistical record verification.

No market/account calls. This does not rerun bootstrap or ridge fitting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

COMPONENTS = ('negative_gap_repair','positive_gap_fade')
MODELS = ('controls','controls+negative_gap_repair','controls+positive_gap_fade','controls+both')


def verify_formula(daily: pd.DataFrame, components: pd.DataFrame) -> dict:
    """Piecewise segment interpretation, separate from native vector min/max."""
    if (tuple(components.columns) != COMPONENTS or not components.index.isin(daily.index).all()
            or components.index.has_duplicates or not components.index.is_monotonic_increasing):
        raise ValueError('Exact declared two-component index required')
    positions = daily.index.get_indexer(components.index)
    if (positions <= 0).any():
        raise ValueError('Real previous complete session required')
    expected = []
    for position in positions:
        row = daily.iloc[position]
        o, h, low, c = (float(row[key]) for key in ('Open','High','Low','Close'))
        p = float(daily.Close.iloc[position-1])
        if (not np.isfinite([o,h,low,c,p]).all() or min(o,h,low,c,p) <= 0
                or h < max(o,c) or low > min(o,c) or h < low):
            raise ValueError('Illegal source OHLC')
        tr = max(h-low, abs(h-p), abs(low-p))
        if tr == 0:
            values = (0.,0.)
        else:
            repaired = (c-o if c < p else p-o) if o < p and c > o else 0.
            faded = (o-c if c > p else o-p) if o > p and c < o else 0.
            values = (repaired/tr, faded/tr)
        expected.append(values)
    np.testing.assert_array_equal(components.to_numpy(dtype=float), np.array(expected))
    return {'status':'PASS', 'formula_rows':len(components),
        'zero_counts':{name:int(components[name].eq(0).sum()) for name in COMPONENTS}}


def independent_ic(x, y, controls=None):
    finite = np.isfinite(x)&np.isfinite(y)
    if controls is not None:
        finite &= np.isfinite(controls).all(axis=1)
    n = int(finite.sum())
    if n < 20:
        return n, None
    a, b = rankdata(x[finite], method='average'), rankdata(y[finite], method='average')
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return n, None
    if controls is None:
        return n, float(spearmanr(x[finite], y[finite]).statistic)
    design = np.column_stack([np.ones(n), *[rankdata(c, method='average') for c in controls[finite].T]])
    residuals = [v-design@np.linalg.lstsq(design,v,rcond=None)[0] for v in (a,b)]
    if any(np.linalg.norm(r) <= 1e-10*np.linalg.norm(v-v.mean()) for r,v in zip(residuals,(a,b),strict=True)):
        return n, None
    return n, float(np.corrcoef(*residuals)[0,1])


def equal_number(actual, expected, tolerance=1e-13):
    if expected is None:
        if actual is not None:
            raise ValueError('Unavailable statistic must retain null')
    else:
        np.testing.assert_allclose(actual, expected, rtol=0, atol=tolerance)


def verify_cost_proxy(values, observed):
    good = np.asarray(values,dtype=float)
    good = good[np.isfinite(good)]
    if observed['n'] != len(good) or (good <= -1).any():
        raise ValueError('Observed return proxy uses every finite legal gross label')
    equal_number(observed['gross_mean'],float(good.mean()) if len(good)>=20 else None)
    expected = float(((1+good)*(.999/1.001)-1).mean()) if len(good)>=20 else None
    equal_number(observed['net_cost_proxy_mean'],expected)
    if observed['account_return'] is not False or observed['diagnostic_only'] is not True:
        raise ValueError('Cost proxy cannot masquerade as actual account return')


def verify_statistics(features, labels, opportunity, result, last_execution_session):
    """Exact original calendars/maturity/counts and independent IC/MSE/groups."""
    index = features.index
    method = result['method']
    if (not isinstance(index,pd.DatetimeIndex) or not index.equals(labels.index)
            or not index.equals(opportunity.index) or index.has_duplicates or not index.is_monotonic_increasing
            or opportunity.dtype != bool or opportunity.isna().any()):
        raise ValueError('All original observations/opportunity must align')
    if tuple(method['components']) != COMPONENTS or len(method['controls']) != 14 or result['signal_n'] != len(index):
        raise ValueError('Full two-component/14-control panel required')
    controls = features.loc[:,method['controls']].to_numpy(dtype=float)
    all_x = features.loc[:,[*method['controls'],*COMPONENTS]].to_numpy(dtype=float)
    sessions = index.append(pd.DatetimeIndex([last_execution_session]))
    if last_execution_session <= index[-1]:
        raise ValueError('Final authorized execution session must follow last signal')
    checks = []
    coverage = []
    for label,horizon in method['labels'].items():
        ends = pd.to_datetime(labels['label_end_'+label]).astype('datetime64[ns]')
        expected = pd.Series(pd.NaT,index=index,dtype='datetime64[ns]')
        n = max(0,len(sessions)-horizon-1)
        expected.iloc[:n] = sessions[horizon+1:].to_numpy()
        pd.testing.assert_series_equal(ends,expected,check_names=False)
        np.testing.assert_array_equal(labels[label].notna(),ends.notna())
        checks.append(label+' maturity and endpoint coverage')
    if set(result['scopes']) != {'all','opportunity'}:
        raise ValueError('Both fixed original scopes required')
    for scope,panel in result['scopes'].items():
        selected = np.ones(len(index),dtype=bool) if scope == 'all' else opportunity.to_numpy()
        if panel['eligible_n'] != int(selected.sum()):
            raise ValueError('Scope row coverage changed')
        for name in COMPONENTS:
            for year in ['ALL',*sorted(set(index.year))]:
                subset = selected if year == 'ALL' else selected&(index.year==year)
                zero = int((subset&features[name].eq(0).to_numpy()).sum())
                coverage.append({'scope':scope,'year':str(year),'component':name,
                    'n':int(subset.sum()),'zero_n':zero,'zero_fraction':zero/int(subset.sum()) if subset.any() else None})
        for label,block in panel['labels'].items():
            y = labels[label].to_numpy(dtype=float)
            ends = pd.to_datetime(labels['label_end_'+label]).astype('datetime64[ns]')
            proxy_enabled = 'mean_net_cost_proxy' in method and label.startswith('return')
            if proxy_enabled:
                verify_cost_proxy(y[selected],block['return_cost_proxy'])
            pooled_groups = {name:{'low':[],'high':[]} for name in COMPONENTS}
            for name in COMPONENTS:
                x = features[name].to_numpy(dtype=float)
                for key,c in (('spearman',None),('partial_rank_ic',controls)):
                    count,value = independent_ic(x[selected],y[selected],None if c is None else c[selected])
                    if block['components'][name][key]['n'] != count:
                        raise ValueError('Correlation count mismatch')
                    equal_number(block['components'][name][key]['value'],value)
                checks.append(scope+' '+label+' '+name+' independent IC')
            wf = block['walk_forward']
            if set(wf['yearly']) != {str(y) for y in range(2021,2027)} or tuple(wf['prediction_records']) != MODELS:
                raise ValueError('Retain all six years and four common models')
            for year,row in wf['yearly'].items():
                year_int = int(year)
                matches = index[index.year == year_int]
                first = matches[0] if len(matches) else None
                if row['first_actual_signaldate'] != (first.isoformat() if first is not None else None):
                    raise ValueError('Wrong actual test-year start')
                finite = np.isfinite(all_x).all(axis=1)&np.isfinite(y)
                tr = selected&finite&(index.year>=2020)&(index.year<year_int)
                tr &= (ends < first).to_numpy() if first is not None else False
                te = selected&finite&(index.year==year_int)
                if (row['common_train_n'],row['common_test_n']) != (int(tr.sum()),int(te.sum())):
                    raise ValueError('Mature train/test counts changed')
                latest = ends[tr].max().isoformat() if tr.any() else None
                if row['latest_train_label_end'] != latest:
                    raise ValueError('Latest training-label maturity changed')
                for name in COMPONENTS:
                    x = features[name].to_numpy(dtype=float)
                    gx = selected&(index.year>=2020)&(index.year<year_int)&np.isfinite(x)&np.isfinite(y)
                    gx &= (ends < first).to_numpy() if first is not None else False
                    test = selected&(index.year==year_int)&np.isfinite(x)&np.isfinite(y)
                    group = row['groups'][name]
                    if (group['train_n'],group['test_n']) != (int(gx.sum()),int(test.sum())):
                        raise ValueError('Group finite maturity coverage changed')
                    if group.get('q25') is not None:
                        q25,q75 = np.quantile(x[gx],[.25,.75],method='linear')
                        equal_number(group['q25'],q25,0)
                        equal_number(group['q75'],q75,0)
                        low,high = test&(x<=q25),test&(x>=q75)
                        overlap = int((low&high).sum())
                        if group['overlap_n'] != overlap:
                            raise ValueError('Group overlap cannot be dropped or disguised')
                        for key,mask in (('low',low),('high',high)):
                            if group[key]['n'] != int(mask.sum()):
                                raise ValueError('Group row count mismatch')
                            equal_number(group[key]['mean'],float(y[mask].mean()) if mask.sum()>=20 else None)
                            pooled_groups[name][key].extend(y[mask].tolist())
                            if proxy_enabled:
                                verify_cost_proxy(y[mask],group[key]['return_cost_proxy'])
                        diff = group['high']['mean']-group['low']['mean'] if group['high']['mean'] is not None and group['low']['mean'] is not None else None
                        equal_number(group['high_minus_low'],diff)
                    else:
                        overlap = None
                    coverage.append({'scope':scope,'label':label,'year':year,'component':name,
                        'low_n':group['low']['n'],'high_n':group['high']['n'],
                        'overlap_n':overlap,'high_minus_low':group['high_minus_low'],
                        'q25':group.get('q25'),'q75':group.get('q75'),'group_reason':group.get('reason'),
                        'meaning':'Overlapping groups are descriptive, not independent portfolios or buy advantages.'})
                checks.append(scope+' '+label+' '+year+' mature counts and zero-tie overlap')
            if proxy_enabled:
                for name in COMPONENTS:
                    for key in ('low','high'):
                        verify_cost_proxy(pooled_groups[name][key],wf['aggregate_groups'][name][key]['return_cost_proxy'])
            common_dates = None
            for model,records in wf['prediction_records'].items():
                dates = [r['signaldate'] for r in records]
                if len(dates) != len(set(dates)):
                    raise ValueError('Duplicated retained prediction')
                if common_dates is None:
                    common_dates = dates
                elif dates != common_dates:
                    raise ValueError('All models must use same predicted dates')
                prediction_index = pd.DatetimeIndex(pd.to_datetime(dates))
                truth = np.array([r['target'] for r in records])
                prediction = np.array([r['prediction'] for r in records])
                baseline = np.array([r['baseline'] for r in records])
                np.testing.assert_array_equal(truth,labels.loc[prediction_index,label].to_numpy())
                metrics = wf['aggregate_models'][model]
                if metrics['n'] != len(records):
                    raise ValueError('Retained prediction count differs')
                equal_number(metrics['mse'],float(np.mean((truth-prediction)**2)) if len(records) else None)
                equal_number(metrics['baseline_mse'],float(np.mean((truth-baseline)**2)) if len(records) else None)
                for year,row in wf['yearly'].items():
                    use = prediction_index.year == int(year)
                    yearly = row['models'][model]
                    if yearly['n'] != row['common_test_n']:
                        raise ValueError('Model finite test coverage differs from common rows')
                    if yearly['mse'] is not None:
                        if int(use.sum()) != yearly['n']:
                            raise ValueError('Annual prediction count mismatch')
                        equal_number(yearly['mse'],float(np.mean((truth[use]-prediction[use])**2)))
                        first = index[index.year==int(year)][0]
                        tr = selected&np.isfinite(all_x).all(axis=1)&np.isfinite(y)&(index.year>=2020)&(index.year<int(year))&(ends<first).to_numpy()
                        np.testing.assert_array_equal(baseline[use],np.full(int(use.sum()),y[tr].mean()))
                    elif use.any():
                        raise ValueError('Unavailable model cannot retain predictions')
                checks.append(scope+' '+label+' '+model+' retained truth/MSE')
    return {'status':'PASS','checks':checks,'check_count':len(checks), 'coverage':coverage,
        'new_account_evaluations':0,
        'limits':'Independent published-row IC/OLS, maturity/counts/zero mass and overlapping groups, retained truth/MSE. Bootstrap and ECDF/ridge fitting not rerun; financial goal not evaluated.'}
