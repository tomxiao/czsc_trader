"""Independent read-only audit of four existing accounts; no prepare/evaluate calls."""
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import StrategyInputBinding

ROOT=Path(__file__).resolve().parents[5]
HERE=Path(__file__).resolve().parents[1]
OUT=HERE/'others'
def read(p): return json.loads(p.read_bytes())
def mod(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def frame(x): return pd.DataFrame(x['data'])
def close(a,b): np.testing.assert_allclose(a,b,rtol=1e-11,atol=1e-8)
def normalized(f):
    f=f.copy();f.attrs={};f['Date']=pd.to_datetime(f.Date).dt.strftime('%Y-%m-%d');return f.set_index('Date').sort_index()

def main():
    old=mod(HERE.parent/'EX026_20261023/src/study.py','old_inputs_audit')
    adj,raw,_,rules,old_ids=old.inputs(old.sources())
    for f in (adj,raw): f.attrs={}
    prior=read(HERE.parent/'EX027_20261023/others/published_refs.json')
    sr=EvidenceRef.from_dict(prior['materials']['others/own_shares.csv'])
    shares=pd.read_csv(sr.resolve(ROOT))
    oldframes={'market':normalized(adj),'execution':normalized(raw),'shares':normalized(shares)}
    rawidx=normalized(raw)
    ctx=old.context()
    results=read(OUT/'results.json');diagnosis=read(OUT/'account_diagnosis.json')
    records=[];input_checks=[];seen={};decisions={};account_tables={}
    signal_cache={}
    for row in results['rows']:
        cid=row['candidate_id'];ev=read(EvidenceRef.from_dict(row['evidence']).resolve(ROOT))
        req=ev['request_identity']
        assert req['initial_cash']==100000 and req['price_basis']=='HFQ_RESEARCH'
        assert req['pricing']=={'anchor_date':'2024-12-31','anchor_factor':1.0,'basis':'HFQ_RESEARCH','quantity_unit':'RESEARCH_UNIT'}
        assert req['market_rules']==rules
        assert req['input_bindings']==ev['input_bindings']
        for win,b in ev['input_bindings'].items():
            binding=StrategyInputBinding.from_mapping(b)
            assert b['plan']['calculation_dates'][0]=='2024-12-31'
            assert b['plan']['calculation_dates'][-1]=='2026-10-20'
            assert b['plan']['requests']['shares']['end']=='2026-10-19'
            for name in ('market','execution','shares'):
                r=binding.plan.requests[name]
                key=(str(binding.prepared.preparation_id),name,r.start,r.end)
                if key not in seen:
                    got=ctx.data.fetch(r,prepared=binding.prepared);assert got.ready,got.error
                    actual=normalized(got.dataframe)
                    expected=oldframes[name].loc[r.start:r.end]
                    assert list(actual.columns)==list(expected.columns)
                    pd.testing.assert_index_equal(actual.index,expected.index)
                    pd.testing.assert_frame_equal(actual,expected,check_dtype=False,check_exact=True)
                    seen[key]={'name':name,'start':r.start,'end':r.end,'rows':len(actual),'identity':got.identity.content_sha256,'exact_prior_overlap':'PASS'}
                input_checks.append({'candidate':cid,'window':win,**seen[key]})
        for run in ev['runs']:
            win=run['window_id'];summary=row['runs'][win]
            assert run['signal_support']['input_binding']==ev['input_bindings'][win]
            policy=run['signal_support']['execution_policy']['settings']
            assert policy['capital']=={'allocation_fraction':1.0,'fee_rate':.001,'mode':'target_equity_fraction','target_scope':'decision'}
            tables={k:frame(v) for k,v in run['ledgers'].items()}
            a=tables['account_daily'];d=tables['decisions'];f=tables['fills'];t=tables['trades'];o=tables['orders']
            assert len(a)==(434 if win=='full' else 415)
            assert float(a.cash_before.iloc[0])==100000 and int(a.quantity_before.iloc[0])==0
            close(a.equity,a.cash+a.quantity*a.close)
            close(a.cash_before.iloc[1:],a.cash.iloc[:-1]);close(a.quantity_before.iloc[1:],a.quantity.iloc[:-1])
            close(a.close,rawidx.loc[pd.to_datetime(a.date).dt.strftime('%Y-%m-%d'),'Close'])
            close(f.fees,f.quantity*f.price*.001)
            assert (f.quantity%100==0).all() and (f.quantity<=1000000).all()
            fills=f.copy();fills['day']=pd.to_datetime(f.fill_time).dt.strftime('%Y-%m-%d')
            fills['signed_quantity']=np.where(fills.side.eq('BUY'),fills.quantity,-fills.quantity)
            fills['cash_change']=-fills.signed_quantity*fills.price-fills.fees
            daily=fills.groupby('day')[['signed_quantity','cash_change']].sum()
            daykeys=pd.to_datetime(a.date).dt.strftime('%Y-%m-%d')
            flow=daily.reindex(daykeys,fill_value=0)
            close(a.quantity-a.quantity_before,flow.signed_quantity);close(a.cash-a.cash_before,flow.cash_change)
            assert set(f.cycle_id)==set(t.cycle_id) and t.cycle_id.is_unique
            closed=t[t.status.eq('CLOSED')]
            for tr in closed.itertuples():
                cf=f[f.cycle_id.eq(tr.cycle_id)]
                assert int(cf.loc[cf.side.eq('BUY'),'quantity'].sum())==int(cf.loc[cf.side.eq('SELL'),'quantity'].sum())
                assert pd.Timestamp(tr.exit_date)==pd.to_datetime(cf.fill_time).max()
            eq=[100000.]+a.equity.astype(float).tolist();peak=eq[0];dd=0.
            for v in eq: peak=max(peak,v);dd=max(dd,1-v/peak)
            net=eq[-1]/eq[0]-1;cagr=(eq[-1]/eq[0])**(252/len(a))-1
            exits=pd.to_datetime(closed.exit_date).dt.strftime('%Y-%m-%d').tolist()
            count=[sum(x in set(daykeys.iloc[i-59:i+1]) for x in exits) for i in range(59,len(a))]
            calc={'net_return':net,'cagr':cagr,'dd':dd,'fees':float(f.fees.sum()),'closed':len(closed),'frequency_median':float(np.median(count)),'frequency_good':sum(x>=3 for x in count),'frequency_windows':len(count)}
            for k,v in calc.items(): close(v,summary[k])
            benchmark=frame(run['buyhold']['account_daily'])
            bvals=[100000.]+benchmark.equity.astype(float).tolist();bpeak=100000.;bdd=0.
            for v in bvals:bpeak=max(bpeak,v);bdd=max(bdd,1-v/bpeak)
            bcagr=(bvals[-1]/100000.)**(252/len(a))-1
            close(bdd,summary['benchmark_dd']);close(bcagr,summary['benchmark_cagr'])
            if win=='full':
                gates={'return':cagr>=1.5*bcagr if bcagr>0 else cagr>0,'relative_drawdown':dd<=.8*bdd,'absolute_drawdown':dd<=.25,'frequency_median':np.median(count)>=6,'frequency_coverage':sum(x>=3 for x in count)>=338}
                assert gates==summary['checks'] and bool(all(gates.values()))==summary['center_pass']
            else:
                assert bool(net>.9158029150000013)==summary['return_superior']
                assert bool(dd<.07248663749114126)==summary['dd_superior']
            # Every actual decision agrees with a separate scalar reconstruction on old snapshots.
            if cid not in signal_cache:
                closevals=adj.Close.to_numpy(float);dates=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').tolist();sv=normalized(shares).TotalShare.to_dict()
                age=0;weight=0.;locked_positive=False;srows=[]
                for j,day in enumerate(dates):
                    if day<'2024-12-31':continue
                    funding=sv[dates[j-1]]/sv[dates[j-21]]-1
                    avg=sum(closevals[j-19:j+1])/20;ret=closevals[j]/closevals[j-5]-1
                    trend=closevals[j]>avg and ret>0
                    if age and (not trend or age>=3):age=0;weight=0.
                    elif age:age+=1
                    elif trend:age=1;locked_positive=funding>0;weight=.5 if cid=='C3301' and funding<=0 else 1.
                    srows.append({'signal_date':day,'target_position':weight,'intent_age':age,'funding20':funding,'return5':ret,'average20':avg,'locked_funding_positive':locked_positive})
                signal_cache[cid]=pd.DataFrame(srows).set_index('signal_date')
            for col in ('target_position','intent_age','funding20','return5','average20'):
                close(d[col],signal_cache[cid].loc[pd.to_datetime(d.signal_date).dt.strftime('%Y-%m-%d'),col])
            decisions[(cid,win)]=d;account_tables[(cid,win)]=a
            # A fill within an existing holding is a resize, not another CLOSED cycle.
            held=a[['date','quantity_before']].copy();held['day']=pd.to_datetime(held.date).dt.strftime('%Y-%m-%d')
            merged=fills.merge(held[['day','quantity_before']],on='day',validate='many_to_one')
            merged=merged.merge(d[['decision_id','target_position','intent_age']],on='decision_id',validate='many_to_one')
            assert len(merged)==len(fills) and not merged[['quantity_before','target_position','intent_age']].isna().any().any()
            resize=merged[(merged.quantity_before>0)&(merged.target_position>0)]
            rec={'candidate':cid,'window':win,**calc,'fills':len(f),'orders':len(o),'ending_quantity':int(a.quantity.iloc[-1]),'within_holding_resize_fills':len(resize),'within_holding_buys':int(resize.side.eq('BUY').sum()),'within_holding_sells':int(resize.side.eq('SELL').sum()),'half_target_resize_fills':int(resize.target_position.eq(.5).sum()),'resize_fees':float(resize.fees.sum()),'distinct_resize_cycles':int(resize.cycle_id.nunique()),'cash_quantity_equity_reconciliation':'PASS','decision_scalar_checks':len(d)}
            expected_diag=diagnosis[f'{cid}_{win}'];groups={}
            for cyc,cf in f.groupby('cycle_id'):
                first=cf.sort_values('fill_time').iloc[0]
                positive=signal_cache[cid].loc[pd.Timestamp(first.signal_date).strftime('%Y-%m-%d'),'locked_funding_positive']
                group='expansion_locked' if positive else 'weak_locked'
                z=groups.setdefault(group,{'closed':0,'gross_yuan':0.,'fees_yuan':0.,'net_yuan':0.,'positive_cycles':0,'negative_cycles':0})
                gross=float(np.where(cf.side.eq('SELL'),cf.quantity*cf.price,-cf.quantity*cf.price).sum())
                fees=float(cf.fees.sum());netcyc=gross-fees
                z['closed']+=1;z['gross_yuan']+=gross;z['fees_yuan']+=fees;z['net_yuan']+=netcyc
                z['positive_cycles']+=int(netcyc>0);z['negative_cycles']+=int(netcyc<0)
            for group,vals in groups.items():
                for k,v in vals.items():close(v,expected_diag['groups'][group][k])
            gross_total=sum(g['gross_yuan'] for g in groups.values())
            close(gross_total-f.fees.sum(),a.equity.iloc[-1]-100000)
            close(gross_total,expected_diag['gross_yuan'])
            close(rec['within_holding_buys'],expected_diag['additional_buy_fills'])
            close(rec['within_holding_sells'],expected_diag['partial_sell_fills'])
            rec.update({'cycle_group_audit':'PASS','gross_yuan':gross_total,'groups':groups})
            records.append(rec)
    pairs=[]
    for win in ('full','s011_common'):
        x=decisions[('C3300',win)];y=decisions[('C3301',win)]
        for c in ('signal_date','valid_session','intent_age','trend_ok','funding20','return5','average20','close'):pd.testing.assert_series_equal(x[c],y[c])
        assert (x.target_position.gt(0)==y.target_position.gt(0)).all()
        assert ((y.target_position==x.target_position)|(y.target_position.eq(.5)&x.target_position.eq(1))).all()
        pairs.append({'window':win,'same_entry_exit_intentions':'PASS','half_target_days':int(y.target_position.eq(.5).sum())})
    for cid in ('C3300','C3301'):
        x=decisions[(cid,'full')].set_index('signal_date');y=decisions[(cid,'s011_common')].set_index('signal_date')
        for c in ('target_position','intent_age','funding20'):pd.testing.assert_series_equal(x.loc[y.index,c],y[c])
    output={'status':'PASS','scope':'Independent audit of immutable existing four accounts; no preparation, evaluation, new account or experiment','account_audits':records,'input_overlap_checks':input_checks,'prior_price_identities':old_ids,'prior_share_ref':sr.to_dict(),'paired_arm_checks':pairs,'canonical_common_window_signal_equivalence':'PASS','source_review':{'causal_share_index':'T-1 / T-21; no current-day shares','intent_age':'Entry1; continue2,3; exit next decision, trend-invalid may exit earlier; no same-decision reentry','weight':'Fixed within intention cycle; existing target-equity execution may resize shares','limitations':'T-1 delay enforces temporal indexing, not proof of historical vendor point-in-time revisions; input overlaps exactly match admitted snapshots. Execution market rules equal prior contract; all account close prices match admitted raw snapshot. No additional stress or perturbation accounts.'}}
    (OUT/'independent_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':output['status'],'accounts':records,'input_checks':len(input_checks)},ensure_ascii=False))

if __name__=='__main__':main()
