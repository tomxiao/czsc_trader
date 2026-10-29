"""Independent event, denominator, cost and bootstrap-artifact reconciliation."""
from collections import Counter,defaultdict
import gzip
import json
from math import fsum,isclose
import numpy as np
from study import WORK,HORIZONS,NAMES,PRIMARY,read,save,digest


def load(name):
    return json.loads(gzip.decompress((WORK/f'others/{name}.json.gz').read_bytes()))


def verify_match(control,selected,summary):
    groups=defaultdict(list)
    for r in control:
        if r['price_net_return'] is not None:
            groups[r['stratum']].append(r['price_net_return'])
    good=[r for r in selected if r['price_net_return'] is not None]
    assert summary['count']==len(good)
    if not good:
        assert summary['control_mean'] is None and summary['difference']['count']==0
        return
    controls=[fsum(groups[r['stratum']])/len(groups[r['stratum']]) for r in good]
    delta=[r['price_net_return']-c for r,c in zip(good,controls,strict=True)]
    assert isclose(fsum(controls)/len(controls),summary['control_mean'],abs_tol=1e-13)
    assert isclose(fsum(delta)/len(delta),summary['difference']['mean'],abs_tol=1e-13)
    assert summary['control_support']['singleton_target_events']==sum(len(groups[r['stratum']])==1 for r in good)


def verify_summary(pop,summary):
    assert summary['events']==len(pop)
    assert summary['status']==dict(Counter(r['status'] for r in pop))
    assert summary['signal_days']==len({r['date'] for r in pop})
    returns=[r['price_net_return'] for r in pop if r['price_net_return'] is not None]
    assert summary['price']['count']==len(returns)
    if returns:
        assert isclose(summary['price']['mean'],fsum(returns)/len(returns),abs_tol=1e-13)
        assert isclose(summary['price']['win_rate'],sum(r>0 for r in returns)/len(returns),abs_tol=1e-13)


def main():
    analysis=read(WORK/'others/analysis.json')
    for name,expected in analysis['artifacts'].items():
        assert digest(WORK/f'others/{name}.json.gz')==expected
    rows,facts,draws=load('events'),load('signal_facts'),load('bootstrap_draws')
    facts_by={r['i']:r for r in facts}
    assert len(facts_by)==analysis['eligible']
    all_signals={k:set() for k in NAMES}
    for r in facts:
        f=r['facts']
        a=f['close']>f['previous_high65']
        expected={'A':a,'B':f['mean']>f['lag_mean'] and f['previous_close']<=f['previous_mean'] and f['close']>f['mean'],
            'C':f['previous_close']<=f['previous_mean']-2*f['previous_atr'] and f['close']>f['previous_high'],
            'AC':a and f['previous_atr13']<=.7*f['previous_atr65'],
            'AV':a and f['volume']>=1.5*f['volume_median']}
        for k,v in expected.items():
            assert v==(k in r['signals'])
        assert ('AC' not in r['signals'] and 'AV' not in r['signals']) or 'A' in r['signals']
        for k in r['signals']:
            all_signals[k].add(r['i'])
    assert {k:len(v) for k,v in all_signals.items()}==analysis['signal_counts']
    counts=[]
    for n in HORIZONS:
        subset=[r for r in rows if r['n']==n]
        assert len(subset)==analysis['eligible'] and len({r['i'] for r in subset})==len(subset)
        for r in subset:
            assert r['signals']==facts_by[r['i']]['signals']
            if r['status']=='COMPLETE':
                expected=(r['exit_price']-r['entry_price']-.001*(r['entry_price']+r['exit_price']))/(r['entry_price']*1.001)
                assert isclose(expected,r['price_net_return'],abs_tol=1e-13)
            else:
                assert r['price_net_return'] is None
        h=analysis['horizons'][str(n)]
        verify_summary(subset,h['all'])
        parent=[r for r in subset if 'A' in r['signals']]
        for name in NAMES:
            chosen=[r for r in subset if name in r['signals']]
            reduced=[]
            boundary=-1
            for r in chosen:
                if r['i']>boundary:
                    reduced.append(r)
                    boundary=r['i']+n+1
            value=h['signals'][name]
            for mode,pop in [('raw',chosen),('nonoverlap',reduced)]:
                verify_summary(pop,value[mode])
                verify_match(subset,pop,value['matched_'+mode])
                if name in ('AC','AV'):
                    verify_match(parent,pop,value['parent_matched_'+mode])
                if n==PRIMARY[name]:
                    variants=[('',value['bootstrap_'+mode])]
                    if name in ('AC','AV'):
                        variants.append(('_parent',value['parent_bootstrap_'+mode]))
                    for suffix,intervals in variants:
                        actual=draws[f'{name}_{n}_{mode}{suffix}']
                        for field,draw_key in [('price_mean','price_mean'),('matched_difference','matched_difference')]:
                            good=[v for v in actual[draw_key] if v is not None]
                            saved=intervals[field]
                            assert saved['valid_replicates']==len(good)
                            assert saved['empty_replicates']==1000-len(good)
                            if good:
                                assert np.allclose(saved['interval_95'],np.quantile(good,[.025,.975]),rtol=0,atol=1e-14)
                            else:
                                assert saved['interval_95'] is None
            counts.append(f'{name}:{n}')
    assert analysis['legacy_reproduction']['status']=='PASS'
    assert analysis['legacy_reproduction']['exact_event_rows']==analysis['eligible']*3
    save(WORK/'others/result_validation.json',{'status':'PASS','analysis_sha256':digest(WORK/'others/analysis.json'),
        'verification_source_sha256':digest(WORK/'src/verify.py'),'event_rows':len(rows),
        'signal_facts':len(facts),'cells_checked':counts,'bootstrap_series':len(draws),
        'checks':['source_artifact_hashes','five_expression_predicates','conditional_subsets',
                  'costs_and_nonobservable_labels','raw_and_greedy_denominators',
                  'matched_general_and_parent_controls','retained_bootstrap_intervals',
                  'old_PAT_and_three_horizon_reproduction'],
        'scope':'Diagnostic event reconciliation; no account acceptance or independent market validation.'})
    print('RESULT_VALIDATION PASS',len(rows),'events',len(counts),'cells',flush=True)


if __name__=='__main__':
    main()
