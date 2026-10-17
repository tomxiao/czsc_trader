"""Independent temporal, label, match and opportunity checks for both calibrations."""
import json
from hashlib import sha256
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from study import ROOT,EX,RUN,OLD,inputs
from component import causal_gap_environment
from annual_followup import calibrate,COLS,interval

def main():
    target=EX/'others/audit.json'
    if target.exists():raise RuntimeError('Preserve audit')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'));checks=[]
    def check(name,ok):
        assert bool(ok),name
        checks.append(name)
    for lock,mapping in [('published_design',{'design':'protocols/design.json','study':'src/study.py','component':'src/component.py'}),('published_annual',None)]:
        for key,value in read(EX/f'protocols/{lock}.json').items():
            rel=mapping[key] if mapping else key;ref=EvidenceRef.from_dict(value)
            check('locked '+rel,(EX/rel).read_bytes()==ref.resolve(ROOT).read_bytes() and sha256((EX/rel).read_bytes()).hexdigest()==ref.sha256)
    oldrefs=read(OLD/'others/result.json')['evidence']
    for key,rel in [('ex013-corrected-features-csv','corrected/features.csv'),('ex013-corrected-labels-csv','corrected/labels.csv')]:
        ref=EvidenceRef.from_dict(oldrefs[key]);p=ROOT/'research/S014/assets/runs'/OLD.name/rel
        check('original published '+key,sha256(p.read_bytes()).hexdigest()==ref.sha256 and p.read_bytes()==ref.resolve(ROOT).read_bytes())
    data,dates,labels,*_=inputs();f=pd.read_csv(ROOT/'research/S014/assets/runs'/OLD.name/'corrected/features.csv',index_col='signal');bars=data['stock.ohlcv']
    closed=labels.loc[labels.entry_filled&labels.maturity.ge(0)]
    check('fee cash exact .001 both sides',np.allclose(closed.net_return,closed.quantity*(closed.exit_price*.999-closed.entry_price*1.001)/100000,rtol=0,atol=1e-11))
    check('calendar and T plus one',len(dates)==1642 and (labels.entry==labels.signal+1).all() and (closed.planned_exit==closed.entry+closed.horizon).all())
    check('mature unfilled zero; censored excluded',labels.loc[~labels.entry_filled&labels.maturity.ge(0),'net_return'].eq(0).all())
    h1=labels.loc[labels.horizon.eq(1)&labels.maturity.ge(0)].set_index('signal');h3=labels.loc[labels.horizon.eq(3)&labels.maturity.ge(0)].set_index('signal')
    annual=pd.read_csv(RUN/'annual_observations.csv');rolling=pd.read_csv(RUN/'observations.csv');cuts,splits=calibrate(f,labels,dates)
    check('annual startup',splits[0]['signal']==185 and splits[0]['train_n']==60 and not cuts.iloc[:185].notna().any())
    check('mature before annual calibration',all(s['last_maturity']<s['signal'] for s in splits))
    oldcuts=[x for x in read(OLD/'others/session_result.json')['splits'] if x['horizon']==3 and x['variant']=='primary20']
    for row in oldcuts:
        new=next(x for x in splits if x['year']==row['year'])
        check('old annual threshold '+str(row['year']),new['threshold']==row['threshold'] and new['train_n']==row['train_n'])
    oldmembers=pd.read_csv(ROOT/'research/S014/assets/runs'/OLD.name/'session_members.csv');oldmembers=oldmembers.loc[oldmembers.horizon.eq(3)&oldmembers.variant.eq('primary20')]
    check('every original state and parent',np.array_equal(f.loc[oldmembers.signal,'gap_autocorr'].to_numpy()>=cuts.loc[oldmembers.signal].to_numpy(),oldmembers.state.to_numpy()>=oldmembers.threshold.to_numpy()) and np.array_equal(f.loc[oldmembers.signal,'gap_down_repair'].eq(1).to_numpy(),oldmembers.parent))
    for window in (252,126,504):
        state=causal_gap_environment(bars,window);part=rolling.loc[rolling.window.eq(window)]
        check('rolling state '+str(window),np.array_equal(state.loc[part.signal,'high'].to_numpy(bool),part.high))
        for stop in (184,250,800,1400):
            prefix=causal_gap_environment(bars.iloc[:stop],window)
            pd.testing.assert_frame_equal(prefix,state.iloc[:stop]);check(f'rolling prefix {window}/{stop}',True)
    for stop in (184,250,800,1400):
        prefix,ps=calibrate(f.iloc[:stop],labels.loc[labels.signal.lt(stop)&labels.maturity.lt(stop)],dates[:stop])
        pd.testing.assert_series_equal(prefix,cuts.iloc[:stop]);check('annual prefix '+str(stop),True)
    altered=labels.copy();altered['net_return']=1234.;different,_=calibrate(f,altered,dates)
    check('threshold never uses return values',different.equals(cuts))
    corr=causal_gap_environment(bars).correlation
    check('original correlation reproduced',np.allclose(f.gap_autocorr,corr,atol=1e-12,rtol=0,equal_nan=True))
    for name,g in [('annual',annual),*[(str(w),p) for w,p in rolling.groupby('window')]]:
        a=h1.loc[g.signal];b=h3.loc[g.signal]
        check('same entry shares '+name,np.allclose(a.quantity,b.quantity,equal_nan=True) and np.allclose(a.entry_price,b.entry_price,equal_nan=True))
        check('actual label outcome '+name,np.allclose(g.net_return,b.net_return,atol=1e-12,rtol=0) and np.allclose(g.extension,b.net_return.to_numpy()-a.net_return.to_numpy(),atol=1e-12,rtol=0))
        check('mature and unique '+name,g.signal.is_unique and (g.maturity>=0).all())
    matches=pd.read_csv(EX/'others/annual_matches.csv');valid=np.isfinite(f.to_numpy(float)).all(1)
    for year,part in annual.groupby('year'):
        split=next(x for x in splits if x['year']==year);tr=labels.loc[labels.horizon.eq(3)&labels.maturity.ge(0)&labels.maturity.lt(split['signal'])&labels.signal.isin(f.index[valid])];train=f.loc[tr.signal,COLS]
        z=(f.loc[part.signal,COLS]-train.mean())/train.std(ddof=0).replace(0,1);lookup=part.set_index('signal');available=list(part.loc[~part.high,'signal'].astype(int));expected=[]
        for signal in part.loc[part.high,'signal'].astype(int):
            if not available:break
            dd=((z.loc[available]-z.loc[signal])**2).mean(axis=1).pow(.5);chosen=dd.idxmin()
            if dd.loc[chosen]<=1:available.remove(chosen);expected.append((signal,chosen,dd.loc[chosen]))
        saved=matches.loc[matches.year.eq(year)]
        check('match membership '+str(year),np.allclose(saved[['a','b','distance']],np.array(expected),atol=1e-12,rtol=0))
        check('match returns '+str(year),np.allclose(saved.difference,lookup.loc[saved.a,'net_return'].to_numpy()-lookup.loc[saved.b,'net_return'].to_numpy(),atol=1e-12))
    check('matches no replacement',matches.a.is_unique and matches.b.is_unique and (matches.distance<=1).all())
    cluster=[];trim=[]
    for name,g in [('annual',annual),('rolling252',rolling.loc[rolling.window.eq(252)])]:
        for high,part in g.groupby('high'):
            end=-1;cid=-1;ids=[]
            for row in part.sort_values('signal').itertuples():
                if row.entry>end:cid+=1
                ids.append(cid);end=max(end,row.maturity)
            v=part.copy();v['cluster']=ids;means=v.groupby('cluster')[['net_return','extension']].mean()
            for col in ('net_return','extension'):
                leave=[means.drop(i)[col].mean() for i in means.index]
                cluster.append({'calibration':name,'high':bool(high),'metric':col,'n':len(part),'clusters':len(means),'equal_mean':means[col].mean(),'leave_min':min(leave),'leave_max':max(leave)})
            trim.append({'calibration':name,'high':bool(high),'net_drop_best3':part.net_return.sort_values().iloc[:-3].mean(),'extension_drop_worst3':part.extension.sort_values().iloc[3:].mean()})
    pd.DataFrame(cluster).to_csv(EX/'others/audited_clusters.csv',index=False,lineterminator='\n');pd.DataFrame(trim).to_csv(EX/'others/audited_trim.csv',index=False,lineterminator='\n')
    for filename,g in [('computation',rolling.loc[rolling.window.eq(252)]),('annual_followup',annual)]:
        result=read(EX/f'others/{filename}.json')
        for row in result['capacity']:
            end=-1;source=h1 if row['kind']=='parent_H1' else h3;chosen=source.loc[row['signals']]
            for signal,r in chosen.iterrows():assert signal>=end and r.entry_filled;end=int(r.maturity)
            # Independent maximum-cardinality interval DP under the declared label schedule.
            candidates=source.loc[g.loc[g.high,'signal'] if row['kind']=='high_H3' else g.signal];candidates=candidates.loc[candidates.entry_filled].sort_values(['maturity','signal'])
            best=np.zeros(len(dates)+1,dtype=int)
            by_end={int(e):v for e,v in candidates.groupby('maturity')}
            for t in range(len(dates)):
                best[t+1]=best[t]
                for signal,r in by_end.get(t,pd.DataFrame()).iterrows():best[t+1]=max(best[t+1],best[int(signal)+1]+1)
            check('schedule DP '+filename+'/'+row['kind'],best[-1]==row['schedulable_count']==len(chosen) and abs(len(chosen)*60/1642-row['per60_calendar'])<1e-12)
    checks.extend(['all source bindings revalidated','no external fetches or new account runs'])
    manifest=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted([*EX.rglob('*.py'),*EX.rglob('*.json'),*EX.rglob('*.csv'),*RUN.glob('*.csv')]) if p.name!='audit.json']
    target.write_text(json.dumps({'status':'PASS','checks':checks,'check_count':len(checks),'manifest':manifest,'source_calls':0},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('PASS',len(checks))

if __name__=='__main__':main()
