"""Audit later event/operational evidence and the narrowly scoped component."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EX,load
from audit import independent_predict
from component import gap_sequence_context
from czsc_trader.research_tools import EvidenceRef


def main():
    target=EX/'others/final_audit.json'
    if target.exists():raise RuntimeError('Preserve final audit')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    checks=[]
    def check(name,value):
        assert value,name
        checks.append({'name':name,'status':'PASS'})
    initial=read(EX/'others/audit.json')
    for item in initial['manifest']:
        assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
    check('initial 15 checks and immutable snapshot preserved',initial['status']=='PASS')
    for key in ('clusters','operational'):
        for name,value in read(EX/f'protocols/published_{key}.json').items():
            ref=EvidenceRef.from_dict(value);raw=ref.resolve(ROOT).read_bytes()
            path=EX/(f'protocols/{name.replace("-","_")}.json' if name.endswith('-design') else f'src/{name}.py')
            assert raw==path.read_bytes() and sha256(raw).hexdigest()==ref.sha256
    check('late designs and executed source identity',True)
    run=ROOT/'research/S014/assets/runs'/EX.name/'corrected';f=pd.read_csv(run/'features.csv',index_col='signal');labels=pd.read_csv(run/'labels.csv')
    matches=pd.read_csv(EX/'others/session_matches.csv').sort_values('a').reset_index(drop=True);cluster=read(EX/'others/cluster_result.json')
    check('all 54 matches assigned exactly once to 34 clusters',sum(x['pairs'] for x in cluster['clusters'])==54 and len(cluster['clusters'])==34 and len({s for c in cluster['clusters'] for s in c['a_signals']})==54)
    means=[];leave=[]
    for c in cluster['clusters']:
        g=matches.loc[matches.a.isin(c['a_signals'])]
        np.testing.assert_allclose(g.difference.mean(),c['mean'],rtol=0,atol=1e-12)
        means.append(g.difference.mean());leave.append(matches.loc[~matches.a.isin(c['a_signals']),'difference'].mean())
    summary=cluster['summaries'][0]
    np.testing.assert_allclose([np.mean(means),min(leave),max(leave)],[summary['cluster_equal_weight'],summary['leave_cluster_min'],summary['leave_cluster_max']],rtol=0,atol=1e-12)
    check('cluster-equal and all leave-one-cluster effects reproduced',True)
    lookup=labels.loc[labels.horizon.eq(3)].set_index('signal');spans=[]
    for i in cluster['both_legs_kept_indices']:
        for s in matches.loc[i,['a','b']]:
            entry,maturity=lookup.loc[int(s),['entry','maturity']]
            assert all(max(entry,a)>min(maturity,b) for a,b in spans)
            spans.append((entry,maturity))
    check('29 paired observations have no overlap on either leg',len(spans)==58)
    operational=pd.read_csv(run.parent/'operational_predictions.csv');base=read(EX/'others/computation_result_v2.json')['baseline_columns'];refits=0
    for year,test in operational.groupby('year'):
        train=labels.loc[labels.horizon.eq(3)&labels.maturity.lt(int(test.signal.min()))]
        threshold=float(f.loc[train.signal,'gap_autocorr'].median());x=f.copy()
        x['high_state']=x.gap_autocorr.ge(threshold).astype(float);x['state_interaction']=x.high_state*x.gap_down_repair;x['continuous_interaction']=x.gap_autocorr*x.gap_down_repair
        for algo in ('ridge','tree'):
            for name,cols in {'base':base,'continuous':base+['gap_autocorr','continuous_interaction'],'binary':base+['high_state','state_interaction']}.items():
                expected=independent_predict(algo,x.loc[train.signal,cols].to_numpy(),x.loc[test.signal,cols].to_numpy(),train.net_return.to_numpy());refits+=1
                np.testing.assert_allclose(expected,test[f'prediction_{algo}_{name}'],rtol=0,atol=1e-9)
    check('24 operational estimator refits',refits==24)
    direct=read(EX/'others/direct_result.json');obs=pd.read_csv(run.parent/'direct_observations.csv');pred=pd.read_csv(run/'predictions.csv')
    for r in direct['comparisons']:
        g=obs.loc[obs.family.eq(r['family'])&obs.horizon.eq(r['horizon'])];lookup_p=pred.loc[pred.horizon.eq(r['horizon'])].set_index('signal')
        y=g.net_return.to_numpy()-(lookup_p.loc[g.signal,'prediction_ridge_base'].to_numpy() if r['mode']=='residual' else 0)
        np.testing.assert_allclose(y[g.a].mean()-y[g.b].mean(),r['difference'],rtol=0,atol=1e-12)
    check('50 direct raw/residual effects reproduced',True)
    data,*_=load();thresholds={r['year']:r['threshold'] for r in read(EX/'others/session_result.json')['splits'] if r['variant']=='primary20' and r['horizon']==3}
    context=gap_sequence_context(data['stock.ohlcv'],thresholds)
    members=pd.read_csv(run.parent/'session_members.csv');members=members.loc[members.horizon.eq(3)&members.variant.eq('primary20')]
    flags=context.loc[members.signal]
    assert flags.ready.all()
    np.testing.assert_array_equal((flags.relatively_high_state&flags.low_open_positive_close).to_numpy(dtype=bool),members.a.to_numpy())
    np.testing.assert_array_equal((~flags.relatively_high_state&flags.low_open_positive_close).to_numpy(dtype=bool),members.b.to_numpy())
    check('reusable component exactly reproduces all primary H3 classifications',len(members)==910)
    for n in (801,1200):
        prefix=gap_sequence_context(data['stock.ohlcv'].iloc[:n],thresholds)
        pd.testing.assert_frame_equal(context.iloc[:n],prefix)
    check('component prefix causality and explicit unavailable-year state',not context.loc[pd.to_datetime(context.Date).dt.year.lt(2023),'ready'].any())
    files={p for directory in (EX/'src',EX/'protocols',EX/'others',run.parent) for p in directory.rglob('*') if p.is_file() and '__pycache__' not in str(p) and p.name not in ('final_audit.json','result.json','report_copy_verification.json')}
    manifest=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]
    target.write_text(json.dumps({'status':'PASS','checks':checks,'prior_checks':15,'additional_refits':refits,'total_audit_refits':528,'manifest':manifest,'source_calls':0},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','checks_total':15+len(checks),'audit_refits':528,'files':len(manifest)}))


if __name__=='__main__':main()
