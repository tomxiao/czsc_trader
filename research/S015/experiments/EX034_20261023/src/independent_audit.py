"""Independent scalar/dynamic-programming audit; no new experiment or account."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import importlib.util
import json
import math
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from trading_execution_engine import DailyQuote, MarketExecutionRules, OrderSpec, resolve_fill

HERE=Path(__file__).resolve().parents[1]
ROOT=HERE.parents[3]
N=0
def read(p): return json.loads(p.read_bytes())
def check(actual,expected,path=''):
    global N
    N+=1
    if isinstance(expected,dict):
        assert actual.keys()==expected.keys(),(path,actual.keys(),expected.keys())
        for k,v in expected.items(): check(actual[k],v,path+'/'+str(k))
    elif isinstance(expected,(list,tuple)):
        assert len(actual)==len(expected),path
        for i,(a,b) in enumerate(zip(actual,expected)): check(a,b,path+'/'+str(i))
    elif expected is None: assert actual is None or pd.isna(actual),path
    elif isinstance(expected,(float,np.floating)):
        assert np.isclose(actual,expected,rtol=1e-9,atol=1e-8,equal_nan=True),(path,actual,expected)
    else: assert actual==expected,(path,actual,expected)

def summ(values):
    values=[float(v) for v in values if pd.notna(v)]
    pos=[v for v in values if v>0];neg=[v for v in values if v<0]
    return dict(n=len(values),mean_return=sum(values)/len(values)/100000 if values else None,
                positive_n=len(pos),negative_n=len(neg),positive_yuan=sum(pos),negative_yuan=-sum(neg),net_yuan=sum(values))
def ratio(a,b):return a/b if b else None
def contrast(frame,yes,no,label):
    a=summ(frame.loc[frame[yes],label]);b=summ(frame.loc[frame[no],label])
    return {'in':a,'out':b,'delta':a['mean_return']-b['mean_return'] if a['n'] and b['n'] else None,
            'rejected_loss_fraction':ratio(b['negative_yuan'],a['negative_yuan']+b['negative_yuan']),
            'missed_profit_fraction':ratio(b['positive_yuan'],a['positive_yuan']+b['positive_yuan']),
            'rejected_loss_count_fraction':ratio(b['negative_n'],a['negative_n']+b['negative_n']),
            'missed_profit_count_fraction':ratio(b['positive_n'],a['positive_n']+b['positive_n'])}
def resamples():
    rng=np.random.default_rng(13)
    return [np.concatenate([np.arange(t,t+20) for t in rng.integers(0,415,22)])[:434] for _ in range(499)]
def boot(frame,label,a,b):
    diffs=[]
    for idx in resamples():
        sub=frame.iloc[idx];av=sub.loc[sub[a],label].dropna();bv=sub.loc[sub[b],label].dropna()
        if len(av) and len(bv):diffs.append((float(av.mean())-float(bv.mean()))/100000)
    return dict(valid_draws=len(diffs),ci95=np.percentile(diffs,[2.5,97.5]).tolist() if diffs else None)
def match(frame,label):
    rows=list(frame[frame[label].notna()].itertuples());pairs=[]
    for a in rows:
        if not a.accepted:continue
        candidates=[]
        for b in rows:
            if b.rejected and b.period==a.period and abs(b.r5-a.r5)<=.05 and .5<=b.vol20/a.vol20<=2:
                distance=((b.r5-a.r5)/.05)**2+(math.log(b.vol20/a.vol20)/math.log(2))**2
                candidates.append((distance,b.position,b))
        if not candidates:continue
        distance,_,b=min(candidates,key=lambda t:t[:2])
        p=dict(accepted_position=int(a.position),rejected_position=int(b.position),difference=(getattr(a,label)-getattr(b,label))/100000,distance=distance)
        for c in ('r5','vol20','confirmation_change','breakout_stretch'):p[c+'_difference']=getattr(a,c)-getattr(b,c)
        pairs.append(p)
    return dict(matched_accepted_n=len(pairs),eligible_accepted_n=sum(r.accepted for r in rows),
                unique_rejected_n=len(set(p['rejected_position'] for p in pairs)),delta=np.mean([p['difference'] for p in pairs]) if pairs else None,
                balance={c:np.mean([p[c+'_difference'] for p in pairs]) if pairs else None for c in ('r5','vol20','confirmation_change','breakout_stretch')},pairs=pairs)
def freq(frame,mask,dates):
    lookup={d:i for i,d in enumerate(dates)}
    intervals=[(lookup[r.entry_date],lookup[r.actual_exit_date]) for r in frame.itertuples() if getattr(r,mask) and r.status=='CLOSED']
    counts=[]
    # Maximum-cardinality interval scheduling by DP, independently of study's greedy rule.
    # All intervals end after they start; same-day exit/entry is deliberately allowed.
    for end in range(59,434):
        eligible=[(s,e) for s,e in intervals if end-59<=e<=end]
        dp=[0]*(end+1)
        for t in range(end+1):
            carry=dp[t-1] if t else 0
            choices=[dp[s]+1 for s,e in eligible if e==t]
            dp[t]=max([carry]+choices)
        counts.append(dp[-1])
    return dict(max_nonoverlap_median=float(np.median(counts)),windows_at_least3=sum(n>=3 for n in counts),total_windows=375,counts=counts,
                not_ruled_out_by_bound=bool(np.median(counts)>=6 and sum(n>=3 for n in counts)>=338))

def main():
    frozen=read(HERE/'others/protocol_refs.json')
    for name,folder in [('study.py','src'),('price_path.json','protocols')]:
        check(EvidenceRef.from_dict(frozen[name]).resolve(ROOT).read_bytes(),(HERE/folder/name).read_bytes(),name)
    inp=read(HERE/'others/input_refs.json');proto=read(HERE/'protocols/price_path.json')
    sr=EvidenceRef.from_dict(inp['prior_source']);authenticated=sr.resolve(ROOT)
    path=HERE.parent/'EX026_20261023/src/study.py'
    check(path.read_bytes(),authenticated.read_bytes(),'legacy_loader_identity')
    spec=importlib.util.spec_from_file_location('authenticated_legacy_input_loader',path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    refs={k:EvidenceRef.from_dict(v) for k,v in inp['source_inputs'].items()}
    for r in refs.values():r.resolve(ROOT)
    # Reopen already prepared, hash-pinned snapshots through the public DFLS loader.
    adj,raw,bars,rules,identities=old.inputs(refs)
    for f in (adj,raw,bars):f.attrs={}
    check(identities,inp['data_identities'],'identities')
    saved=pd.read_csv(HERE/'others/adjusted_prices.csv')
    for c in ('Open','High','Low','Close'):np.testing.assert_allclose(saved[c],adj[c],rtol=1e-12)
    x=pd.read_csv(HERE/'others/features.csv');result=read(HERE/'others/results.json')
    prices=adj.to_dict('records');expected=[]
    for i in range(75,509):
        b=i-2;boundary=max(float(r['High']) for r in prices[b-20:b])
        trs=[max(float(prices[j]['High'])-float(prices[j]['Low']),abs(float(prices[j]['High'])-float(prices[j-1]['Close'])),abs(float(prices[j]['Low'])-float(prices[j-1]['Close']))) for j in range(b-20,b)]
        atr=sum(trs)/20;close=float(prices[i]['Close']);prior=float(prices[i-1]['Close']);bc=float(prices[b]['Close'])
        anchor=bc>boundary;accepted=anchor and prior>boundary and close>boundary
        r=dict(date=str(pd.Timestamp(prices[i]['Date']).date()),anchor_date=str(pd.Timestamp(prices[b]['Date']).date()),
               anchor=anchor,accepted=accepted,rejected=anchor and not accepted,
               retest=accepted and min(float(prices[i-1]['Low']),float(prices[i]['Low']))<=boundary+.25*atr and close>prior,
               boundary=boundary,atr_anchor=atr,close=close,r5=close/float(prices[i-5]['Close'])-1,
               vol20=float(np.std([float(prices[j]['Close'])/float(prices[j-1]['Close'])-1 for j in range(i-19,i+1)],ddof=1)),
               confirmation_change=close/bc-1,breakout_stretch=(bc-boundary)/atr,position=i-75,
               period=sum(i-75>=bound for bound in (100,184,268,352)))
        expected.append(r)
        check(x.iloc[i-75].to_dict(),r,'features/'+str(i-75))
    check(result['signal_counts'],{c:sum(r[c] for r in expected) for c in ('anchor','accepted','rejected','retest')},'counts')
    er=EvidenceRef.from_dict(inp['prior_labels']);events=pd.read_csv(er.resolve(ROOT));extra=pd.read_csv(HERE/'others/additional_events.csv')
    all_events=pd.concat([events,extra],ignore_index=True);market=MarketExecutionRules.from_dict(rules)
    def resolve(order,j):
        p=prices[j];day=pd.Timestamp(p['Date'])
        return resolve_fill(order,session_open=float(p['Open']),session_time=day.replace(hour=9,minute=30).to_pydatetime(),
            intraday_touches=(),session_limits=market.for_session(day.date()),daily_quote=DailyQuote(float(p['Low']),float(p['High'])))
    def floor(v):return float(Decimal(str(v)).quantize(Decimal('.001'),rounding=ROUND_FLOOR))
    for e in all_events.itertuples():
        i=e.position+75;j=i+1;k=i+e.horizon+1
        rawclose=float(raw.Close.iloc[i]);scale=float(adj.Close.iloc[i])/rawclose
        limit=min(floor(rawclose*1.01),floor(floor(rawclose*1.1)-.001))*scale
        quantity=min(1000000,int(Decimal(100000)/(Decimal(str(limit))*Decimal('1.001')*100))*100)
        check(e.buy_limit,limit,'limit');check(e.quantity,quantity,'quantity')
        if j>=len(prices):check(e.status,'NO_NEXT_SESSION','status');continue
        buy=resolve(OrderSpec('BUY','LIMIT',quantity,limit),j)
        check(e.entry_date,str(pd.Timestamp(prices[j]['Date']).date()),'entry_date')
        if not buy.filled:check(e.status,'BUY_UNFILLED','status');continue
        fee=quantity*buy.price*.001;entry=quantity*(float(prices[j]['Close'])-buy.price)
        for field,value in [('buy_price',buy.price),('buy_fee',fee),('entry_gross',entry),('entry_net',entry-fee)]:check(getattr(e,field),value,field)
        exit_index=None
        for t in range(k,len(prices)):
            sell=resolve(OrderSpec('SELL','MARKET',quantity,None),t)
            if sell.filled:exit_index=t;break
        if exit_index is None:
            check(e.status,'EXIT_RIGHT_CENSORED' if k>=len(prices) else 'SELL_UNFILLED_AT_END','status')
        else:
            check(e.status,'CLOSED','status');sf=quantity*sell.price*.001;gross=quantity*(sell.price-buy.price)
            for field,value in [('sell_price',sell.price),('sell_fee',sf),('gross',gross),('net',gross-fee-sf),('subsequent_gross',gross-entry),('exit_delay',exit_index-k)]:check(getattr(e,field),value,field)
            check(e.actual_exit_date,str(pd.Timestamp(prices[exit_index]['Date']).date()),'exit_date')
    st=pd.read_csv(HERE/'others/structure_events.csv')
    check(len(st),int(x.accepted.sum()),'structure_count')
    for r in st.itertuples():
        f=x.iloc[r.position];h=5;invalid=None
        for k in range(1,6):
            j=75+r.position+k
            if j<len(prices) and float(prices[j]['Close'])<=f.boundary:h=k;invalid=str(pd.Timestamp(prices[j]['Date']).date());break
        check(r.structural_horizon,h,'structure_horizon');check(r.invalidation_date,invalid,'invalidation_date')
        ev=all_events[(all_events.position==r.position)&(all_events.horizon==h)].iloc[0]
        for c in ('status','net','entry_date','actual_exit_date','buy_fee','sell_fee'):check(getattr(r,c),ev[c],'structure_'+c)
    for label,h in [('net',1),('net',3),('net',5),('entry_net',1)]:
        ev=events[events.horizon==h][['position','status','net','entry_net','entry_date','actual_exit_date']]
        g=x.merge(ev,on='position');g['accepted_no_retest']=g.accepted&~g.retest
        if label=='net':g.loc[g.status!='CLOSED','net']=np.nan
        out=result['targets'][f'{label}_h{h}']
        check(out['acceptance'],contrast(g,'accepted','rejected',label),'acceptance')
        check(out['retest'],contrast(g,'retest','accepted_no_retest',label),'retest')
        check(out['all_days'],summ(g[label]),'all_days')
        check(out['matched'],match(g,label),'matched')
        check(out['acceptance_bootstrap'],boot(g,label,'accepted','rejected'),'bootstrap')
        check(out['retest_bootstrap'],boot(g,label,'retest','accepted_no_retest'),'bootstrap')
        for a,b in proto['segments']:check(out['periods'][f'{a}:{b}'],contrast(g[(g.position>=a)&(g.position<b)],'accepted','rejected',label),'period')
        total=summ(g[label])
        for mask in ('accepted','retest'):
            ss=summ(g.loc[g[mask],label]);ns=summ(g.loc[~g[mask],label])
            check(out['selection'][mask],dict(selected=ss,not_selected=ns,caught_loss_fraction=ratio(ns['negative_yuan'],total['negative_yuan']),
                missed_profit_fraction=ratio(ns['positive_yuan'],total['positive_yuan']),status=g.loc[g[mask],'status'].value_counts().to_dict()),'selection')
        if label=='net':
            for mask in ('anchor','accepted','retest'):check(result['frequency'][f'h{h}'][mask],freq(g,mask,x.date.tolist()),'frequency_DP')
    pairs=st.merge(events[events.horizon==5][['position','net','status']],on='position',suffixes=('','_fixed'))
    p=pairs[(pairs.status=='CLOSED')&(pairs.status_fixed=='CLOSED')].copy();p['delta']=p.net-p.net_fixed
    structural=dict(n=len(p),structure=summ(p.net),fixed5=summ(p.net_fixed),mean_delta=float(p.delta.mean()/100000),
        improved_n=int((p.delta>0).sum()),worsened_n=int((p.delta<0).sum()),early_exit_n=int((p.structural_horizon<5).sum()),status=st.status.value_counts().to_dict())
    axis=np.full(434,np.nan)
    for r in p.itertuples():axis[r.position]=r.delta/100000
    draws=[float(np.nanmean(axis[idx])) for idx in resamples() if np.isfinite(axis[idx]).any()]
    structural['bootstrap']=dict(valid_draws=len(draws),ci95=np.percentile(draws,[2.5,97.5]).tolist())
    check(result['structure'],structural,'structure_result')
    sg=st.merge(x[['position','accepted','retest']],on='position')
    for mask in ('accepted','retest'):check(result['frequency']['structure'][mask],freq(sg,mask,x.date.tolist()),'structure_frequency_DP')
    receipt=dict(status='PASS',checks=N,features_recomputed=434,event_rows_reexecuted=len(all_events),structure_events_checked=len(st),
        bootstrap_contrasts=9,bootstrap_draws_each=499,frequency_series_dynamic_programming=11,windows_each=375,
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),frozen_source_sha256=frozen['study.py']['sha256'],
        data_identities=identities,
        scope=['Authenticated frozen protocol/source and prior event evidence','Independent scalar features from hash-pinned prepared DFLS data',
               'Public TXE execution reconstruction and fee arithmetic for all prior and additional event rows','Structure horizon and same-event h5 pairing',
               'All group, segment, matching, bootstrap, opportunity-loss denominators','Independent dynamic-programming optimum versus greedy frequency upper bound'],
        findings=['No implementation discrepancy found','Frequency bound is mathematical maximum for recorded fixed event intervals with same-day turnover allowed; any feasible subset is bounded above',
                  'Matching uses contemporaneous known features but is descriptive and reuses controls; not a forward predictor or causal identification',
                  'Structure exit horizon is a maximum decision horizon; unfilled market exits may occur later under retry contract'],
        limitations=['Not independent out-of-sample validation; repeated development-pool exposure','Audit shares public TXE engine and prepared-data loader, not independently validated engine internals',
                     'No supplier historical publication-clock or revised-price PIT proof','Independent overlapping events do not form an account; sums are not portfolio PnL',
                     'Frequency upper bound only rules out these frozen entries/exits, not every alternative price-action strategy','No new strategy qualification, continuous account or search'])
    (HERE/'others/independent_audit.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    print(json.dumps(receipt,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
