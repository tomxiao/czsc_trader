"""Independent reconciliation of fixed labels, samples and summary arithmetic."""
from collections import Counter,defaultdict
import gzip
import json
from math import fsum,isclose
import numpy as np
from study import WORK,HORIZONS,NAMES,PRIMARY,read,save,digest


def main():
    analysis=read(WORK/'others/analysis.json')
    for name,expected in analysis['artifacts'].items():
        assert digest(WORK/f'others/{name}.json.gz')==expected
    def load(name):
        return json.loads(gzip.decompress((WORK/f'others/{name}.json.gz').read_bytes()))
    events,facts,draws=load('events'),load('signal_facts'),load('bootstrap_draws')
    assert len(facts)==analysis['eligible']
    facts_by={r['i']:r for r in facts}
    assert len(facts_by)==len(facts)
    assert {name:sum(r[name] for r in facts) for name in NAMES}==analysis['signals']
    for r in facts:
        expected=r['center_gain']>0 and r['p']<r['m'] and r['repair_space']>=.0017298986606429072
        assert r['permission']==expected and (not r['entry_signal'] or r['permission'])
    counts=[]
    for n in HORIZONS:
        rows=events[str(n)]
        assert len(rows)==len(facts)
        groups=defaultdict(list)
        for r in rows:
            assert r['signals']==[name for name in NAMES if facts_by[r['i']][name]]
            if r['status']=='COMPLETE':
                expected=(r['exit_price']-r['entry_price']-.001*(r['entry_price']+r['exit_price']))/(1.001*r['entry_price'])
                assert isclose(expected,r['price_net_return'],abs_tol=1e-14)
                groups[r['stratum']].append(r['price_net_return'])
            else:
                assert r['price_net_return'] is None
        all_good=[r['price_net_return'] for r in rows if r['price_net_return'] is not None]
        overall=analysis['horizons'][str(n)]['all']
        assert overall['events']==len(rows) and overall['price']['count']==len(all_good)
        assert isclose(overall['price']['mean'],fsum(all_good)/len(all_good),abs_tol=1e-14)
        for name in NAMES:
            chosen=[r for r in rows if name in r['signals']]
            reduced=[]
            end=-1
            for r in chosen:
                if r['i']>end:
                    reduced.append(r)
                    end=r['i']+n+1
            value=analysis['horizons'][str(n)]['signals'][name]
            for mode,pop in [('raw',chosen),('nonoverlap',reduced)]:
                summary=value[mode]
                assert summary['events']==len(pop) and summary['status']==dict(Counter(r['status'] for r in pop))
                good=[r for r in pop if r['price_net_return'] is not None]
                assert summary['price']['count']==len(good)
                if good:
                    mean=fsum(r['price_net_return'] for r in good)/len(good)
                    control=fsum(fsum(groups[r['stratum']])/len(groups[r['stratum']]) for r in good)/len(good)
                    assert isclose(summary['price']['mean'],mean,abs_tol=1e-14)
                    assert isclose(value['matched_'+mode]['control_mean'],control,abs_tol=1e-14)
                    assert isclose(value['matched_'+mode]['difference']['mean'],mean-control,abs_tol=1e-14)
                if n==PRIMARY:
                    for field in ('price_mean','matched_difference'):
                        raw=[v for v in draws[f'{name}_{n}_{mode}'][field] if v is not None]
                        result=value['bootstrap_'+mode][field]
                        assert result['valid_replicates']==len(raw)
                        assert np.allclose(result['interval_95'],np.quantile(raw,[.025,.975]),rtol=0,atol=1e-14)
            counts.append(f'{name}:{n}')
    reproduction=read(WORK/'others/order_reproduction.json')
    assert reproduction['status']=='PASS' and reproduction['orders']==109 and reproduction['fills']==108
    assert read(WORK/'others/input_identity.json')['signal_rows_exactly_reproduced']==434
    save(WORK/'others/result_validation.json',{'status':'PASS','analysis_sha256':digest(WORK/'others/analysis.json'),
        'verification_source_sha256':digest(WORK/'src/verify.py'),'event_rows':sum(map(len,events.values())),
        'cells':counts,'scope':'Independent summary arithmetic and retained draw quantiles; source signals/orders verified during run, not a second complete account replay.'})
    print('RESULT_VALIDATION_PASS',sum(map(len,events.values())),flush=True)


if __name__=='__main__':
    main()
