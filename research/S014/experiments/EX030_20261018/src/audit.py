"""Independent EX030 arithmetic and population audit, never an account replay."""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
CHECKS = Counter()


def check(actual, expected, label):
    if expected is None or (isinstance(expected, float) and np.isnan(expected)):
        assert actual is None or pd.isna(actual), (label, actual, expected)
    elif isinstance(expected, (float, np.floating)):
        assert np.isclose(actual, expected, rtol=1e-10, atol=1e-11), (label, actual, expected)
    else:
        assert actual == expected, (label, actual, expected)
    CHECKS[label.split(':')[0]] += 1


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_inputs():
    path = EX.parent / 'EX017_20261017/src/audit_accounts.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('ex030_audit_inputs', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    frames = module.load_frames()
    names = ('stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')
    return [frames[name].set_index(pd.to_datetime(frames[name].Date)).sort_index() for name in names]


def reconstruct_features(close, dates):
    # Explicit rolling windows and independent state transitions; no study import.
    local_anchor = persistent_anchor = local_start = None
    local_id = persistent_id = 0
    old_unreclaimed = False
    already_recovered = False
    previous_break = False
    previous_eval_closes = []
    expected = []
    evaluation_count = 0
    for index, (date, price) in enumerate(zip(dates, close)):
        is_evaluation = date >= pd.Timestamp('2020-01-02')
        evaluation_count += int(is_evaluation)
        floor = min(previous_eval_closes[-5:]) if len(previous_eval_closes) >= 5 else None
        ready = evaluation_count >= 60 and floor is not None
        broke = ready and price < floor
        if broke and not previous_break:
            local_anchor = floor
            local_start = index
            local_id += 1
            already_recovered = False
        if broke and not old_unreclaimed:
            persistent_anchor = floor
            persistent_id += 1
            old_unreclaimed = True
        qualified = ready and not broke
        first = qualified and local_anchor is not None and not already_recovered
        if first:
            already_recovered = True

        def classify(anchor):
            if not qualified:
                return 'ineligible'
            if anchor is None:
                return 'unanchored'
            return 'true_reclaim' if price >= anchor else 'apparent_recovery'

        expected.append(dict(i=index, date=str(date.date()), year=date.year,
            ready=ready, broken=broke, qualified=qualified, floor=floor, close=price,
            local_anchor=local_anchor, persistent_anchor=persistent_anchor,
            episode=local_id, persistent_episode=persistent_id, break_start=local_start,
            break_age=None if local_start is None else index-local_start,
            local_state=classify(local_anchor), persistent_state=classify(persistent_anchor),
            first_recovery=first,
            local_distance=None if local_anchor is None else price/local_anchor-1))
        if old_unreclaimed and price >= persistent_anchor:
            old_unreclaimed = False
        previous_break = broke
        if is_evaluation:
            previous_eval_closes.append(price)
    return expected


def cents(value, rounding=ROUND_FLOOR):
    return float((Decimal(str(value))*100).to_integral_value(rounding=rounding)/100)


def independent_fills(market, raw, limits, status):
    buys, sells = {}, {}
    scale = market.Close/raw.Close
    for index in range(1, len(market)):
        date = market.index[index]
        state = status.loc[date, 'Status']
        assert state in ('TRADING', 'SUSPENDED')
        if state == 'SUSPENDED':
            buys[index] = sells[index] = None
            continue
        bar = market.iloc[index]
        down = float(limits.loc[date, 'DownLimit']*scale.iloc[index])
        up = float(limits.loc[date, 'UpLimit']*scale.iloc[index])
        tick = .01*scale.iloc[index]
        prior = float(raw.Close.iloc[index-1])
        limit = min(cents(prior*1.01), cents(cents(prior*1.1)-.01, ROUND_HALF_UP))*scale.iloc[index-1]
        bound_tolerance = max(abs(down), abs(up))*1e-10
        touch_tolerance = max(abs(limit), abs(bar.Open), abs(bar.Low), abs(bar.High))*1e-12
        if limit < down-bound_tolerance or limit > up+bound_tolerance:
            buy = None
        elif bar.Open <= limit+touch_tolerance:
            buy = float(bar.Open)
        elif bar.Low <= limit+touch_tolerance:
            buy = float(limit)
        else:
            buy = None
        if abs(bar.Open-down) <= abs(down)*1e-10:
            adjusted = float(bar.Open+tick)
            sell = adjusted if adjusted <= bar.High+abs(adjusted)*1e-12 else None
        else:
            sell = float(bar.Open)
        buys[index], sells[index] = buy, sell
    return buys, sells


def dist(values):
    values = np.asarray(values, dtype=float)
    count = len(values)
    if not count:
        return dict(n=0, mean=None, median=None, q10=None, positive_contribution=None,
            negative_contribution=None, positive_n=0, negative_n=0, without_top3=None, without_top5=None)
    order = sorted(values)
    return dict(n=count, mean=sum(values)/count, median=float(np.median(values)),
        q10=float(np.quantile(values, .1)), positive_contribution=sum(v for v in values if v>0)/count,
        negative_contribution=sum(v for v in values if v<0)/count, positive_n=int(sum(values>0)),
        negative_n=int(sum(values<0)), without_top3=sum(order[:-3])/(count-3) if count>3 else None,
        without_top5=sum(order[:-5])/(count-5) if count>5 else None)


def sample_indices(indices, horizon):
    result = []
    for index in indices:
        if not result or index >= result[-1]+horizon+1:
            result.append(index)
    return set(result)


def known_distribution(values):
    values = np.array([float(v) for v in values if pd.notna(v)])
    return dict(n=len(values), mean=None if not len(values) else float(values.mean()),
        median=None if not len(values) else float(np.median(values)),
        q10=None if not len(values) else float(np.quantile(values,.1)),
        q90=None if not len(values) else float(np.quantile(values,.9)))


def audit_summaries(result, labels):
    keys=[tuple(r[k] for k in ('window','population','horizon','anchor','year','state')) for r in result['summaries']]
    expected={(w,p,h,a,y,s) for w in ('ALL','THROUGH_2025') for p in ('first_recovery','all_qualified')
        for h in (1,3,10) for a in ('local','persistent') for y in ('ALL',*range(2020,2027))
        for s in ('true_reclaim','apparent_recovery','unanchored')}
    check(set(keys),expected,'summary_population')
    check(len(keys),len(set(keys)),'summary_unique')
    for row in result['summaries']:
        d = labels[(labels.window == row['window']) & (labels.horizon == row['horizon'])]
        if row['population'] == 'first_recovery':
            d = d[d.first_recovery]
        selected = sample_indices(d.i.tolist(), row['horizon'])
        whole=d[(d.outcome=='CLOSED') & d.i.isin(selected)].sort_values('entry_i')
        overall_overlap=sum(b<=a for a,b in zip(whole.exit_i.tolist()[:-1],whole.entry_i.tolist()[1:]))
        check(row['scheduled_whole_population_overlap_pairs'],overall_overlap,'whole_spacing_overlap')
        if row['year'] != 'ALL':
            d = d[d.year == row['year']]
        d = d[d[row['anchor']+'_state'] == row['state']]
        closed = d[d.outcome == 'CLOSED']
        spaced = closed[closed.i.isin(selected)]
        expectations = dict(attempts=len(d), filled=sum(d.outcome.isin(['CLOSED','OPEN'])),
            closed=len(closed), open=sum(d.outcome=='OPEN'), buy_unfilled=sum(d.outcome=='BUY_UNFILLED'),
            no_next_session=sum(d.outcome=='NO_NEXT_SESSION'))
        for key, value in expectations.items():
            check(row[key], value, 'summary_counts:'+key)
        for name, subset in [('returns', closed), ('scheduled_spaced', spaced)]:
            for key, value in dist(subset.net_return).items():
                check(row[name][key], value, 'summary_distribution:'+key)
        episode_column = 'episode' if row['anchor']=='local' else 'persistent_episode'
        episode_average = None if closed.empty else closed.groupby(episode_column).net_return.mean().mean()
        check(row['episode_equal_mean'], episode_average, 'summary_episode_equal')
        check(row['episode_count'],closed[episode_column].nunique(),'summary_episode_count')
        for name in ('break_age','local_distance'):
            for key,value in known_distribution(d[name]).items():
                check(row[name][key],value,'summary_known_'+name)
        order=spaced.sort_values('entry_i')
        overlap=sum(b<=a for a,b in zip(order.exit_i.tolist()[:-1],order.entry_i.tolist()[1:]))
        check(row['scheduled_actual_overlap_pairs'],overlap,'state_spacing_overlap')
        for name,value,applicable in [('rolling_break','rolling_break_after',None),
            ('local_loss','old_level_loss_after','old_loss_applicable'),
            ('local_reclaim','old_level_reclaim_after','reclaim_applicable')]:
            risk=d if applicable is None else d[d[applicable]]
            event=risk[risk[value].notna()]
            noevent=risk[risk[value].isna()]
            expected=dict(at_risk=len(risk),inapplicable=len(d)-len(risk),observed=len(event),
                horizon_censored=sum(noevent.observed_future_sessions==row['horizon']),
                cutoff_censored=sum(noevent.observed_future_sessions<row['horizon']))
            for key,answer in expected.items():
                check(row['persistence'][name][key],answer,'persistence_denominator')
            for key,answer in known_distribution(event[value]).items():
                check(row['persistence'][name]['event_time'][key],answer,'persistence_time')


def audit_contrasts(result, labels, dates):
    keys=[tuple(r[k] for k in ('window','population','horizon','anchor')) for r in result['contrasts']]
    expected={(w,p,h,a) for w in ('ALL','THROUGH_2025') for p in ('first_recovery','all_qualified')
        for h in (1,3,10) for a in ('local','persistent')}
    check(set(keys),expected,'contrast_population')
    check(len(keys),len(set(keys)),'contrast_unique')
    for row in result['contrasts']:
        d = labels[(labels.window==row['window']) & (labels.horizon==row['horizon'])]
        if row['population']=='first_recovery':
            d=d[d.first_recovery]
        column = row['anchor']+'_state'
        d = d[(d.outcome=='CLOSED') & d[column].isin(['true_reclaim','apparent_recovery'])]
        a=d[d[column]=='true_reclaim']; b=d[d[column]=='apparent_recovery']
        check(row['true_n'], len(a), 'contrast_counts')
        check(row['apparent_n'], len(b), 'contrast_counts')
        check(row['raw_difference'], None if a.empty or b.empty else a.net_return.mean()-b.net_return.mean(), 'contrast_difference')
        # Sample jointly from evaluation-calendar blocks, independently rebuilt.
        cutoff = '2026-10-15' if row['window']=='ALL' else '2025-12-31'
        end = sum(dates <= pd.Timestamp(cutoff))-1
        nblocks=(end-1)//20+1
        aggregates=np.zeros((nblocks,4))
        for record in d.to_dict('records'):
            index=(record['i']-1)//20
            which=0 if record[column]=='true_reclaim' else 1
            aggregates[index,which]+=record['net_return']
            aggregates[index,which+2]+=1
        random=np.random.default_rng(17)
        bootstrap=[]
        for _ in range(2000):
            counts=np.bincount(random.integers(0,nblocks,size=nblocks),minlength=nblocks)
            sums=counts@aggregates
            if sums[2] and sums[3]:
                bootstrap.append(sums[0]/sums[2]-sums[1]/sums[3])
        check(row['block_ci']['valid_replicates'],len(bootstrap),'bootstrap_valid')
        for key, quantile in [('low',.025),('high',.975)]:
            check(row['block_ci'][key], None if not bootstrap else float(np.quantile(bootstrap,quantile)), 'bootstrap_interval')
        cells=defaultdict(lambda:[[],[]])
        for record in d.to_dict('records'):
            age=record['break_age']; group='1' if age<=1 else '2-5' if age<=5 else '6plus'
            which=0 if record[column]=='true_reclaim' else 1
            cells[(record['year'],group)][which].append(record['net_return'])
        pairs=[(key,values) for key,values in cells.items() if all(values)]
        weights=sum(min(len(x),len(y)) for _,(x,y) in pairs)
        numerator=sum(min(len(x),len(y))*(np.mean(x)-np.mean(y)) for _,(x,y) in pairs)
        covered=sum(len(x)+len(y) for _,(x,y) in pairs)
        check(row['stratified_difference'],None if not weights else numerator/weights,'stratified_difference')
        check(row['stratified_covered'],covered,'stratified_coverage')
        check(row['stratified_total'],len(d),'stratified_coverage')


def main():
    output=EX/'others/independent_audit.json'
    if output.exists():
        raise RuntimeError('Preserve completed independent audit')
    upstream=[]
    def block(*args, **kwargs):
        upstream.append(1)
        raise RuntimeError('Audit has no upstream authorization')
    requests.sessions.Session.request=block
    result=read(EX/'others/analysis.json')
    features=pd.read_csv(EX/'others/features.csv')
    labels=pd.read_csv(EX/'others/labels.csv')
    market,raw,limits,status=load_inputs()
    dates=market.index
    for path, expected in result['source_sha256'].items():
        check(sha256((ROOT/path).read_bytes()).hexdigest(),expected,'input_hash')
    for name,expected in result['output_sha256'].items():
        check(sha256((EX/f'others/{name}.csv').read_bytes()).hexdigest(),expected,'output_hash')
    expected_features=reconstruct_features(market.Close.tolist(),dates)
    check(len(features),len(expected_features),'feature_population')
    for actual,expected in zip(features.to_dict('records'),expected_features):
        for name,value in expected.items():
            check(actual[name],value,'feature:'+name)
    check(result['evaluation_sessions'],sum(dates>=pd.Timestamp('2020-01-02')),'metadata_population')
    check(result['ready_sessions'],sum(r['ready'] for r in expected_features),'metadata_population')
    check(result['first_recoveries'],sum(r['first_recovery'] for r in expected_features),'metadata_population')
    check(result['local_break_episodes'],max(r['episode'] for r in expected_features),'metadata_population')
    check(result['never_anchored_qualified'],sum(r['local_state']=='unanchored' for r in expected_features),'metadata_population')
    expected_cross=Counter()
    for row in expected_features:
        if row['qualified']:
            expected_cross[('all_qualified',row['local_state'],row['persistent_state'])]+=1
        if row['first_recovery']:
            expected_cross[('first_recovery',row['local_state'],row['persistent_state'])]+=1
    actual_cross={(r['population'],r['local_state'],r['persistent_state']):r['n'] for r in result['anchor_cross_table']}
    check(actual_cross,dict(expected_cross),'anchor_cross_table')
    buys,sells=independent_fills(market,raw,limits,status)
    expected_keys=set()
    for window,cutoff in [('ALL','2026-10-15'),('THROUGH_2025','2025-12-31')]:
        end=sum(dates<=pd.Timestamp(cutoff))-1
        for state in expected_features:
            if state['qualified'] and state['i']<=end:
                expected_keys.update((window,state['i'],h) for h in (1,3,10))
    actual_keys=[(r.window,r.i,r.horizon) for r in labels.itertuples()]
    check(len(actual_keys),len(set(actual_keys)),'label_unique')
    check(set(actual_keys),expected_keys,'label_population')
    for row in labels.to_dict('records'):
        cutoff='2026-10-15' if row['window']=='ALL' else '2025-12-31'
        end=sum(dates<=pd.Timestamp(cutoff))-1
        index=int(row['i']); entry=index+1; horizon=row['horizon']
        for name,value in expected_features[index].items():
            check(row[name],value,'label_feature:'+name)
        check(row['entry_i'],entry if entry<=end else None,'entry_session')
        expected_outcome='NO_NEXT_SESSION' if entry>end else 'BUY_UNFILLED' if buys[entry] is None else None
        if expected_outcome:
            check(row['outcome'],expected_outcome,'outcome')
            for field in ('entry_price','exit_i','exit_price','net_return','mark_return'):
                check(row[field],None,'unfilled_null:'+field)
        else:
            check(row['entry_price'],buys[entry],'buy_price')
            candidates=[j for j in range(entry+horizon,end+1) if sells[j] is not None]
            exit_index=candidates[0] if candidates else None
            check(row['exit_i'],exit_index,'sell_session')
            check(row['outcome'],'OPEN' if exit_index is None else 'CLOSED','outcome')
            if exit_index is None:
                check(row['net_return'],None,'censored_net')
                check(row['mark_return'],float(market.Close.iloc[end])/(buys[entry]*1.001)-1,'censored_mark')
            else:
                check(row['exit_price'],sells[exit_index],'sell_price')
                check(row['net_return'],sells[exit_index]*.999/(buys[entry]*1.001)-1,'return_fee')
                check(row['mark_return'],None,'closed_mark')
                check(row['sell_delay'],exit_index-(entry+horizon),'sell_delay')
                assert exit_index > entry
        last=min(index+horizon,end)
        check(row['observed_future_sessions'],last-index,'future_observed')
        broken=[j-index for j in range(index+1,last+1) if expected_features[j]['broken']]
        check(row['rolling_break_after'],broken[0] if broken else None,'rolling_persistence')
        check(row['rolling_break_censored'],not broken,'rolling_censor')
        anchor=expected_features[index]['local_anchor']
        loss_at_risk=anchor is not None and market.Close.iloc[index]>=anchor
        reclaim_at_risk=anchor is not None and market.Close.iloc[index]<anchor
        check(row['old_loss_applicable'],loss_at_risk,'loss_applicable')
        check(row['reclaim_applicable'],reclaim_at_risk,'reclaim_applicable')
        loss=[j-index for j in range(index+1,last+1) if market.Close.iloc[j]<anchor] if loss_at_risk else []
        reclaim=[j-index for j in range(index+1,last+1) if market.Close.iloc[j]>=anchor] if reclaim_at_risk else []
        check(row['old_level_loss_after'],loss[0] if loss else None,'old_loss_time')
        check(row['old_level_reclaim_after'],reclaim[0] if reclaim else None,'old_reclaim_time')
        check(row['old_loss_censored'],bool(loss_at_risk and not loss),'old_loss_censor')
        check(row['reclaim_censored'],bool(reclaim_at_risk and not reclaim),'old_reclaim_censor')
    audit_summaries(result,labels)
    audit_contrasts(result,labels,dates)
    bridge=result['counterexample_bridge']
    check(len(bridge),69,'counterexample_count')
    check(sum(r['original']['R_cycle_log']>0 for r in bridge),31,'counterexample_sign')
    check(sum(r['original']['R_cycle_log'] for r in bridge),1.1745165549823025,'counterexample_sum')
    for row in bridge:
        index=dates.get_loc(pd.Timestamp(row['original']['entry_date']))-1
        for name,value in expected_features[index].items():
            check(row['signal_state'][name],value,'counterexample_state:'+name)
    check(result['new_accounts'],0,'scope')
    check(result['new_candidates'],0,'scope')
    check(result['new_upstream_calls'],0,'scope')
    assert not upstream
    evidence_paths=(Path(__file__),EX/'protocols/design.json',EX/'protocols/published_design.json',EX/'src/study.py',EX/'others/analysis.json',EX/'others/features.csv',EX/'others/labels.csv')
    report=dict(status='PASS',checks=sum(CHECKS.values()),checks_by_category=dict(CHECKS),
        feature_rows=len(features),label_rows=len(labels),summary_rows=len(result['summaries']),
        contrast_rows=len(result['contrasts']),new_accounts=0,new_upstream_calls=0,
        method='Independent explicit-window feature reconstruction, arithmetic daily fills, all labels and summary distributions, joint block bootstrap and common-support strata. No study.py import or account evaluation.',
        manifest=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(p.read_bytes()).hexdigest()) for p in evidence_paths])
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:report[k] for k in ('status','checks','feature_rows','label_rows','summary_rows','contrast_rows')}))


if __name__=='__main__':
    main()
