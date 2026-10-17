"""Focused independent arithmetic, identity, temporal and paired-label audit."""
from hashlib import sha256
import importlib.util
import json
import numpy as np
import pandas as pd
from study import ROOT,EX,RUN,OLD,source,features

def main():
    target=EX/'others/audit.json'
    if target.exists():raise RuntimeError('Preserve audit')
    checks=[]
    def check(name,ok):
        assert bool(ok),name
        checks.append({'name':name,'status':'PASS'})
    for filename in ('published_design','published_followup','published_duration'):
        refs=json.loads((EX/'protocols'/f'{filename}.json').read_text(encoding='utf-8'))
        for key,ref in refs.items():
            name={'design-json':'protocols/design.json','study-py':'src/study.py','lock-py':'src/lock.py'}.get(key)
            if name is None:name=('protocols/' if key.endswith('design') or key=='duration_falsification' else 'src/')+key+('.json' if key.endswith('design') or key=='duration_falsification' else '.py')
            check('published source '+name,sha256((EX/name).read_bytes()).hexdigest()==ref['sha256'])
    labels,_=source('ex013-corrected-labels-csv');f,_=source('ex013-corrected-features-csv');g=pd.read_csv(RUN/'observations.csv');d=pd.read_csv(RUN/'duration.csv')
    spec=importlib.util.spec_from_file_location('prior_inputs',OLD/'src/inputs.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    data,dates,original,*_=mod.load();bars=data['stock.ohlcv'];fx=features(bars,f.set_index('signal'))
    closed=labels.loc[labels.entry_filled];expected=closed.quantity*(closed.exit_price*.999-closed.entry_price*1.001)/100000
    check('existing public bindings and two-sided fee cash identities',np.allclose(expected,closed.net_return,rtol=0,atol=1e-11))
    check('unfilled zero and no right-censor fabrication',labels.loc[~labels.entry_filled,'net_return'].eq(0).all() and labels.net_return.notna().all())
    check('entry and planned horizons unchanged',(labels.entry==labels.signal+1).all() and (closed.planned_exit==closed.entry+closed.horizon).all())
    for stop in (750,1000,1300,1600):
        prefix=features(bars.iloc[:stop],f.set_index('signal').loc[lambda x:x.index<stop])
        pd.testing.assert_frame_equal(prefix,fx.loc[prefix.index],check_exact=False,atol=1e-12,rtol=0)
    check('all feature prefixes causal',True)
    result=json.loads((EX/'others/computation.json').read_text(encoding='utf-8'))
    check('all calibration labels mature before test',all(v['max_maturity']<v['first_test'] for v in result['calibration']))
    ses,_=source('ex013-others-session_result-json',False);cuts={v['year']:v['threshold'] for v in ses['splits'] if v['horizon']==3 and v['variant']=='primary20'}
    expected=fx.loc[g.signal,'gap_autocorr'].to_numpy()>=g.year.map(cuts).to_numpy()
    check('H3 state frozen exactly for all horizons',np.array_equal(expected,g.high) and len(g.loc[g.parent])==216 and g.parent_high.sum()==156)
    common=set(g.loc[g.parent,'signal'])
    for h in (1,3,5,10,20):common &= set(labels.loc[labels.horizon.eq(h),'signal'])
    check('paired duration cohort and exclusion identity',set(d.signal)==common and len(d)==211 and set(result['excluded_signals'])==set(g.loc[g.parent,'signal'])-common)
    for h in (1,3,5,10,20):
        q=labels.loc[labels.horizon.eq(h)].set_index('signal').loc[d.signal]
        for c in ('entry','quantity','entry_price'):check(f'paired H{h} '+c,np.allclose(q[c],d[c],atol=1e-12,rtol=0,equal_nan=True))
        check(f'paired H{h} outcomes',np.allclose(q.net_return,d['y'+str(h)],atol=1e-12,rtol=0))
    for row in pd.read_csv(EX/'others/decomposition.csv').itertuples():
        part=g.loc[g.parent&g.high.eq(row.high)]
        if row.year=='WITHOUT2026':part=part.loc[part.year.ne(2026)]
        elif row.year!='ALL':part=part.loc[part.year.eq(int(row.year))]
        check('decomposition '+str(row.year)+str(row.high),len(part)==row.n and abs(part.net_return.mean()-row.mean)<1e-12 and abs(row.positive+row.downside-row.mean)<1e-12)
    matches=pd.read_csv(EX/'others/matches.csv');lookup=g.set_index('signal')
    for name,part in matches.groupby('name'):
        check('no-replacement matches '+name,part.a.is_unique and part.b.is_unique and (part.distance<=1).all())
        check('matched labels '+name,np.allclose(lookup.loc[part.a,'net_return'],part.a_return,atol=1e-12) and np.allclose(lookup.loc[part.b,'net_return'],part.b_return,atol=1e-12))
    raw=pd.read_csv(EX/'others/duration_increment_ci.csv');fixed=pd.read_csv(EX/'others/duration_increment_ci_corrected.csv')
    check('CI export correction preserves every numeric estimate',np.allclose(raw.high,fixed.ci_high) and np.allclose(raw.low,fixed.ci_low) and np.allclose(raw['mean'],fixed['mean']))
    for scope,part in fixed.groupby('scope',sort=False):check('explicit state order '+scope,part.state.tolist()==['low']*5+['high']*5)
    low=pd.read_csv(EX/'others/low_extension_clusters.csv');h1=labels.loc[labels.horizon.eq(1)].set_index('signal')
    check('low-state extension net-cash difference',np.allclose(low.increment,low.net_return-h1.loc[low.signal,'net_return'].to_numpy(),atol=1e-12,rtol=0))
    r=json.loads((EX/'others/duration_check.json').read_text(encoding='utf-8'));allrow=r['low_extension'][0]
    means=low.groupby('cluster').increment.mean();leave=[means.drop(i).mean() for i in means.index]
    check('39 cluster equal and leave-one evidence',len(means)==39 and abs(means.mean()-allrow['cluster_equal'])<1e-12 and abs(max(leave)-allrow['leave_one_max'])<1e-12)
    # Independent four annual nuisance-model refits.
    saved=pd.read_csv(EX/'others/risk_residual_observations.csv');cols=['vol20','abs_gap','intraday','ret20','market_ret5','sector_ret5']
    for year,part in g.groupby('year'):
        tr=labels.loc[labels.horizon.eq(3)&labels.maturity.lt(part.signal.min())];x=fx.loc[tr.signal,cols].to_numpy();z=fx.loc[part.signal,cols].to_numpy()
        center=x.mean(0);scale=x.std(0);scale[scale<1e-12]=1;x=(x-center)/scale;z=(z-center)/scale;y=tr.net_return.clip(upper=0).to_numpy()
        beta=np.linalg.solve(x.T@x+10*np.eye(6),x.T@(y-y.mean()));out=z@beta+y.mean()
        check('annual downside prediction refit '+str(year),np.allclose(out,saved.loc[saved.year.eq(year),'prediction'],atol=1e-12,rtol=0))
    manifest=[]
    for p in sorted([*EX.rglob('*.py'),*EX.rglob('*.json'),*EX.rglob('*.csv'),*RUN.glob('*.csv')]):
        if p.name=='audit.json':continue
        manifest.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()})
    target.write_text(json.dumps({'status':'PASS','checks':checks,'check_count':len(checks),'refits':4,'manifest':manifest,'source_calls':0},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('AUDIT_PASS',len(checks),'checks',len(manifest),'files')
if __name__=='__main__':main()
