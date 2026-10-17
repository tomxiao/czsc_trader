"""First-close repair invalidation: fixed paired execution probes, no account."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1];RUN=ROOT/'research/S014/assets/runs'/EX.name
OLD=ROOT/'research/S014/experiments/EX013_20261017'
RULES=['repair_erased','no_followthrough','relative_intraday_weakness','breakout_rejected']
BASE=['mark','entry_intraday','entry_range','entry_gap','ret20','vol20','market_intraday','sector_intraday','signal_gap','signal_intraday','gap_state']

def load_module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def prepare():
    data,dates,labels,_,_,sources=load_module('prior_inputs',OLD/'src/inputs.py').load()
    stock=data['stock.ohlcv'];raw=data['stock.unadjusted_daily'];anchor=float(stock.Close.iloc[0]/raw.Close.iloc[0]);price=stock[['Open','High','Low','Close']]/anchor
    result=json.loads((OLD/'others/result.json').read_text(encoding='utf-8'))
    def prior(key):
        ref=EvidenceRef.from_dict(result['evidence'][key]);p=ref.resolve(ROOT);assert sha256(p.read_bytes()).hexdigest()==ref.sha256;return p
    f=pd.read_csv(prior('ex013-corrected-features-csv'),index_col='signal');session=json.loads(prior('ex013-others-session_result-json').read_text(encoding='utf-8'))
    cuts={v['year']:v['threshold'] for v in session['splits'] if v['horizon']==3 and v['variant']=='primary20'}
    common=labels.loc[labels.horizon.eq(1)&labels.entry_filled&labels.maturity.ge(0)].set_index('signal');rows=[]
    for h in (3,5):
        later=labels.loc[labels.horizon.eq(h)&labels.entry_filled&labels.maturity.ge(0)].set_index('signal')
        for s in sorted(set(common.index)&set(later.index)&set(f.index)):
            a=common.loc[s];b=later.loc[s];e=int(a.entry);early=int(a.maturity);late=int(b.maturity);q=int(a.quantity)
            assert e<early<=late and a.quantity==b.quantity and a.entry_price==b.entry_price
            x=price.iloc[e];sig=price.iloc[s];ft=f.loc[s];mi=float(np.log(data['market'].Close.iloc[e]/data['market'].Open.iloc[e]));si=float(np.log(data['sector'].Close.iloc[e]/data['sector'].Open.iloc[e]))
            mark=q*(x.Close*.999-a.entry_price*1.001)/100000;year=int(dates[e].year)
            # Historical training uses a raw causal state value; evaluation thresholds are frozen EX013 values.
            state=float(ft.gap_autocorr);parent=bool(ft.gap_down_repair==1)
            overnight=sum(float(price.Open.iloc[j]-price.Close.iloc[j-1]) for j in range(early+1,late+1))
            intraday=sum(float(price.Close.iloc[j]-price.Open.iloc[j]) for j in range(early,late))
            adjustment=float(price.Open.iloc[early]-a.exit_price+b.exit_price-price.Open.iloc[late])
            factor=q*.999/100000;target=float(b.net_return-a.net_return)
            assert abs((overnight+intraday+adjustment)*factor-target)<1e-10
            rows.append({'signal':s,'entry':e,'decision':e,'decision_date':str(dates[e].date()),'year':year,'horizon':h,'early_exit':early,'maturity':late,'quantity':q,
                'entry_price':float(a.entry_price),'early_price':float(a.exit_price),'late_price':float(b.exit_price),'early_net':float(a.net_return),'late_net':float(b.net_return),
                'target':target,'overnight':overnight*factor,'intraday':intraday*factor,'boundary_adjustment':adjustment*factor,
                'parent':parent,'state':state,'state_ready':int(dates[s].year) in cuts,'gap_state':bool(state>=cuts[int(dates[s].year)]) if int(dates[s].year) in cuts else False,
                'mark':float(mark),'entry_intraday':float(np.log(x.Close/x.Open)),'entry_range':float((x.High-x.Low)/x.Close),
                'entry_gap':float(np.log(x.Open/sig.Close)),'ret20':float(ft.ret20),'vol20':float(ft.vol20),'signal_gap':float(ft.gap),'signal_intraday':float(ft.intraday),
                'market_intraday':mi,'sector_intraday':si,
                'repair_erased':bool(x.Close<sig.Open),'no_followthrough':bool(x.Close<sig.Close),
                'relative_intraday_weakness':bool(np.log(x.Close/x.Open)<mi),'breakout_rejected':bool(x.High>sig.High and x.Close<(x.High+x.Low)/2),
                'mark_loss':bool(mark<0),'red_day':bool(x.Close<x.Open)})
    return pd.DataFrame(rows),dates,labels,cuts,sources

def ridge(x,z,y):
    center=x.mean(0);scale=x.std(0);scale[scale<1e-12]=1.;x=(x-center)/scale;z=(z-center)/scale
    return z@np.linalg.solve(x.T@x+10*np.eye(x.shape[1]),x.T@(y-y.mean()))+y.mean()

def block_ci(g,cols,dates):
    idx=g.decision.to_numpy(int);mat=np.zeros((len(dates),len(cols)));count=np.zeros(len(dates));mat[idx]=g[cols];count[idx]=1
    years=[np.flatnonzero((dates.year==y)&(np.arange(len(dates))>=idx.min())&(np.arange(len(dates))<=idx.max())) for y in (2023,2024,2025,2026)]
    rng=np.random.default_rng(15017);draw=[]
    for _ in range(2000):
        ix=np.concatenate([a[((rng.integers(0,len(a),size=(len(a)+19)//20)[:,None]+np.arange(20))%len(a)).ravel()[:len(a)]] for a in years if len(a)])
        if count[ix].sum():draw.append(mat[ix].sum(0)/count[ix].sum())
    v=np.asarray(draw);point=g[cols].mean().to_numpy();sd=v.std(0,ddof=1);safe=np.where(sd>0,sd,1.);crit=np.quantile(np.max(abs(v-point)/safe,axis=1),.95)
    return [{'comparison':c,'mean':float(point[j]),'low':float(np.quantile(v[:,j],.025)),'high':float(np.quantile(v[:,j],.975)),
        'sim_low':float(point[j]-crit*sd[j]),'sim_high':float(point[j]+crit*sd[j])} for j,c in enumerate(cols)]

def main():
    if (EX/'others/computation.json').exists():raise RuntimeError('Preserve results')
    refs=json.loads((EX/'protocols/published_design.json').read_text(encoding='utf-8'))
    for k,rel in [('design','protocols/design.json'),('study','src/study.py')]:assert sha256((EX/rel).read_bytes()).hexdigest()==refs[k]['sha256']
    frame,dates,labels,cuts,sources=prepare();records=[];intervals=[];pairs=[];prediction=[];calibration=[]
    for h in (3,5):
        allh=frame.loc[frame.horizon.eq(h)].copy();test=allh.loc[allh.year.ge(2023)&allh.state_ready&allh.parent].copy()
        for rule in RULES:
            for base in ('hold','mark_loss','red_day'):
                mask=np.zeros(len(test)) if base=='hold' else test[base].astype(float).to_numpy()
                test[rule+'__'+base]=test.target*(mask-test[rule].astype(float))
        for scope,part in [('ALL',test),('WITHOUT2026',test.loc[test.year.ne(2026)]),*[(str(y),g) for y,g in test.groupby('year')],('HIGH',test.loc[test.gap_state]),('LOW',test.loc[~test.gap_state])]:
            for rule in RULES:
                a=part.loc[part[rule]];b=part.loc[~part[rule]]
                for base in ('hold','mark_loss','red_day'):
                    delta=part[rule+'__'+base];keep=[];end=-1
                    for i,row in part.iterrows():
                        if row.entry>end:keep.append(i);end=int(row.maturity)
                    records.append({'horizon':h,'scope':scope,'rule':rule,'base':base,'n':len(part),'exit_n':len(a),
                        'exit_target':float(a.target.mean()) if len(a) else None,'continue_target':float(b.target.mean()) if len(b) else None,
                        'delta':float(delta.mean()),'drop_best3':float(delta.sum()-delta.nlargest(3).clip(lower=0).sum())/len(part),
                        'nonoverlap_n':len(keep),'nonoverlap_delta':float(delta.loc[keep].mean())})
        if h==3:
            cols=[r+'__'+b for r in RULES for b in ('hold','mark_loss','red_day')];intervals=block_ci(test,cols,dates)
        for year,g in test.groupby('year'):
            train=allh.loc[allh.maturity.lt(int(g.decision.min()))].copy();train['gap_state']=train.state.ge(cuts[year]);g=g.copy()
            for rule in RULES:
                train[rule+'_interaction']=train[rule].astype(float)*train.gap_state.astype(float);g[rule+'_interaction']=g[rule].astype(float)*g.gap_state.astype(float)
            aug=BASE+RULES+[r+'_interaction' for r in RULES]
            for name,cols in [('base',BASE),('augmented',aug)]:
                values=ridge(train[cols].to_numpy(float),g[cols].to_numpy(float),train.target.to_numpy())
                for signal,val in zip(g.signal,values):prediction.append({'horizon':h,'year':int(year),'signal':int(signal),'model':name,'prediction':float(val)})
            calibration.append({'horizon':h,'year':int(year),'train_n':len(train),'max_maturity':int(train.maturity.max()),'min_decision':int(g.decision.min())})
            cols=['mark','entry_range','entry_gap','ret20'];center=train[cols].mean();scale=train[cols].std(ddof=0).replace(0,1.);z=(g.set_index('signal')[cols]-center)/scale;lookup=g.set_index('signal')
            for rule in RULES:
                available=list(g.loc[~g[rule],'signal'].astype(int))
                for signal in g.loc[g[rule],'signal'].astype(int):
                    if not available:break
                    dist=np.sqrt(((z.loc[available].to_numpy()-z.loc[signal].to_numpy())**2).mean(1));j=int(np.argmin(dist))
                    if dist[j]>1:continue
                    control=available.pop(j);a=lookup.loc[signal];b=lookup.loc[control]
                    pairs.append({'horizon':h,'year':int(year),'rule':rule,'a':signal,'b':control,'distance':float(dist[j]),'a_target':float(a.target),'b_target':float(b.target),'difference':float(a.target-b.target)})
    RUN.mkdir(parents=True,exist_ok=True);frame.to_csv(RUN/'observations.csv',index=False,lineterminator='\n')
    for name,values in [('annual',records),('matches',pairs),('predictions',prediction)]:pd.DataFrame(values).to_csv(EX/'others'/f'{name}.csv',index=False,lineterminator='\n')
    target={'primary_intervals':intervals,'calibration':calibration,'input_sources':sources,'model_fits':16,'source_calls':0,'account_runs':0,
        'all_observations':len(frame),'primary_parent_n':int(((frame.horizon==3)&frame.parent&frame.year.ge(2023)&frame.state_ready).sum()),'remaining_rounds':9}
    (EX/'others/computation.json').write_text(json.dumps(target,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'primary_intervals':intervals,'n':target['primary_parent_n']}))
if __name__=='__main__':main()
