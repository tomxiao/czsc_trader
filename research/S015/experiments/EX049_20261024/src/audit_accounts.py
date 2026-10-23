"""Independent P1 formal account, bound input, signal and cycle budget audit."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
import json
import importlib.util
from hashlib import sha256
from pathlib import Path
from decimal import Decimal
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import StrategyCandidate,StrategyInputBinding,implementation_sha256
from strategy_evaluator import ReplayEvidence,audit_replay

HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[3];BASE=HERE.parent;OUT=HERE/'others'
def read(p):return json.loads(p.read_bytes())
def close(a,b):np.testing.assert_allclose(a,b,rtol=1e-10,atol=1e-8,equal_nan=True)
def refread(v):return read(EvidenceRef.from_dict(v).resolve(ROOT))
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def normalize(f):
    f=f.copy();f.attrs={};f['Date']=pd.to_datetime(f.Date);return f.set_index('Date').sort_index()
def expected_decisions(features,params):
    rows=[];age=0
    for day,x in features.iterrows():
        available=[v for v in params['schedule'] if v['date']<=day];ready=bool(available) and day!='2024-12-31';prediction=0.
        if ready:
            latest=available[-1];assert latest['train_known_max']<latest['date']<=day;m=latest['models']['path']
            prediction=float(m['beta'][0]+sum((float(x[c])-m['center'][i])/m['scale'][i]*m['beta'][i+1] for i,c in enumerate(m['columns'])))
        permit=ready and (params['family']=='U' or prediction>=0)
        if age>=params['hold']:age=0
        elif age:age+=1
        elif permit:age=1
        rows.append({'signal_date':day,**x.to_dict(),'target_position':float(age>0),'intent_age':age,'model_ready':float(ready),'path_prediction':prediction,'permission':float(permit),'entry_allocation_fraction':params['exposure'] if age else np.nan})
    return pd.DataFrame(rows).set_index('signal_date')
def metric(a,t):
    eq=np.r_[100000.,a.equity.to_numpy(float)];dd=float(np.max(1-eq/np.maximum.accumulate(eq)))
    days=pd.to_datetime(a.date).dt.strftime('%Y-%m-%d').tolist();exits=pd.to_datetime(t.loc[t.status.eq('CLOSED'),'exit_date']).dt.strftime('%Y-%m-%d').tolist();counts=[sum(d in set(days[i-59:i+1]) for d in exits) for i in range(59,len(days))]
    return {'net_return':eq[-1]/100000-1,'cagr':(eq[-1]/100000)**(252/len(a))-1,'dd':dd,'closed':len(exits),'frequency_median':float(np.median(counts)),'frequency_good':sum(v>=3 for v in counts),'frequency_windows':len(counts)}
def main():
    refs=read(OUT/'account_refs.json')
    for key,v in refs.items():assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes()==(HERE/key).read_bytes()
    proto=read(HERE/'protocols/accounts.json');plan=read(HERE/'protocols/plan.json');schedules={(p['family'],p['lag']):read(HERE/f'others/models_{p["family"]}_{p["lag"]}.json') for p in proto['configurations']}
    oldpath=BASE/'EX026_20261023/src/study.py';oldref=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/protocol_refs.json')['study.py']);assert oldpath.read_bytes()==oldref.resolve(ROOT).read_bytes()
    old=module(oldpath,'p1_account_input_loader');adj,raw,bars,rules,ids=old.inputs(old.sources());ctx=old.context()
    shares=pd.read_csv(EvidenceRef.from_dict(plan['sources']['shares']).resolve(ROOT));originals={k:normalize(v) for k,v in [('market',adj),('execution',raw),('intraday',bars),('shares',shares)]};rawidx=originals['execution']
    feature=pd.read_csv(EvidenceRef.from_dict(plan['sources']['price_features']).resolve(ROOT)).set_index('date');cols=['r1','r5','vol20','range20','pressure','return_time_balance','extrema_order','excursion_balance','halfday_balance','range_expansion','prior_range_compression','shock_concentration','gap_energy_share']
    features={}
    for lag in (1,3):
        g=feature[cols].copy();fund=pd.read_csv(EvidenceRef.from_dict(plan['sources'][f'funding_lag{lag}']).resolve(ROOT)).set_index('date');g['state_positive']=(fund.f20>0).astype(float);g['state_zero']=(fund.f20==0).astype(float)
        seed={c:0. for c in g};date_order=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').tolist();seed_position=date_order.index('2024-12-31');share_index=shares.set_index('Date').TotalShare;ratio=float(share_index.loc[date_order[seed_position-lag]]/share_index.loc[date_order[seed_position-lag-20]]-1);seed['state_positive']=float(ratio>0);seed['state_zero']=float(ratio==0)
        features[lag]=pd.concat([pd.DataFrame([seed],index=['2024-12-31']),g])
    cols=list(features[1].columns);results=read(OUT/'results.json');assert len(results['rows'])==7 and results['account_scenarios']==14 and results['precheck_five_ledgers_equal'];accounts=[];input_checks=[];seen={};csvchecks=0;decisions={};se=[];cycles=[]
    for i,row in enumerate(results['rows']):
        cid=row['candidate_id'];assert row['parameters']==proto['configurations'][i];p=row['parameters'];params={**p,'schedule':schedules[p['family'],p['lag']]}
        assert sha256(json.dumps(params['schedule'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==row['schedule_sha256']
        source=HERE/'src/strategy_runtime';files=['strategies/price_information.py'];candidate=StrategyCandidate('S015',cid,{'decision_feedback':'MARKET_INTENT','parameters':params,'runtime':{'module':'strategy_runtime.strategies.price_information','qualname':'PriceInformation','contract_version':2,'source_files':files,'source_sha256':implementation_sha256(files,source_root=source)}},source)
        ev=refread(row['evidence']);assert candidate.runtime_identity_sha256==ev['strategy_identity'];req=ev['request_identity'];assert req['initial_cash']==100000 and req['price_basis']=='HFQ_RESEARCH' and req['market_rules']==rules and req['input_bindings']==ev['input_bindings']
        expected=expected_decisions(features[p['lag']],params)
        for win,b in ev['input_bindings'].items():
            binding=StrategyInputBinding.from_mapping(b)
            for name,original in originals.items():
                rqt=binding.plan.requests[name];key=(str(binding.prepared.preparation_id),name,rqt.start,rqt.end)
                if key not in seen:
                    fetched=ctx.data.fetch(rqt,prepared=binding.prepared);assert fetched.ready,fetched.error;actual=normalize(fetched.dataframe);want=original.loc[rqt.start:rqt.end];pd.testing.assert_index_equal(actual.index,want.index)
                    differing={}
                    for col in want:
                        assert col in actual
                        mask=actual[col].ne(want[col])
                        if mask.any():differing[col]={'rows':int(mask.sum()),'max_absolute':float((actual[col]-want[col]).abs().max())}
                    if differing:assert name=='intraday' and set(differing)=={'Volume'},(name,differing)
                    used=[c for c in want if name!='intraday' or c!='Volume'];pd.testing.assert_frame_equal(actual[used],want[used],check_dtype=False,check_exact=True)
                    seen[key]={'name':name,'rows':len(actual),'identity':fetched.identity.content_sha256,'exact_consumed_fields_overlap':'PASS','unused_field_differences':differing}
                input_checks.append({'candidate':cid,'window':win,**seen[key]})
        for run in ev['runs']:
            win=run['window_id'];summary=row['runs'][win];tables={k:pd.DataFrame(v['data']) for k,v in run['ledgers'].items()};assert run['signal_support']['input_binding']==ev['input_bindings'][win]
            policy=run['signal_support']['execution_policy']['settings']['capital'];assert policy=={'fee_rate':.001,'mode':'signal_cash_fraction','target_scope':'entry_cycle'}
            audit=audit_replay(ReplayEvidence.from_dict(run['replay_evidence']));se.append({'candidate':cid,'window':win,'status':audit.status.value,'checks':list(audit.checks),'reason_codes':list(audit.reason_codes)})
            for name,table in tables.items():
                exported=pd.read_csv(OUT/f'{cid}_{win}_{name}.csv');text_exported=pd.read_csv(OUT/f'{cid}_{win}_{name}.csv',keep_default_na=False);assert set(exported)==set(table) and len(exported)==len(table)
                for c in table:
                    if pd.api.types.is_numeric_dtype(table[c]):close(exported[c],table[c])
                    elif c in ('date','signal_date','valid_session','execution_date','fill_time','entry_date','exit_date','valuation_source_date'):pd.testing.assert_series_equal(pd.to_datetime(exported[c]).astype('datetime64[ns]'),pd.to_datetime(table[c]).astype('datetime64[ns]'),check_names=False)
                    else:assert text_exported[c].astype(str).tolist()==table[c].fillna('').astype(str).tolist(),c
                csvchecks+=1
            a,d,f,o,t=(tables[k] for k in ('account_daily','decisions','fills','orders','trades'));assert len(a)==len(d)==(434 if win=='full' else 415);days=pd.to_datetime(a.date).dt.strftime('%Y-%m-%d');signal=pd.to_datetime(d.signal_date).dt.strftime('%Y-%m-%d')
            assert float(a.cash_before.iloc[0])==100000 and int(a.quantity_before.iloc[0])==0;assert (pd.to_datetime(d.signal_date)<pd.to_datetime(d.valid_session)).all();close(a.equity,a.cash+a.quantity*a.close);close(a.cash_before.iloc[1:],a.cash.iloc[:-1]);close(a.quantity_before.iloc[1:],a.quantity.iloc[:-1]);close(a.close,rawidx.loc[pd.to_datetime(a.date),'Close'])
            for c in cols+['target_position','intent_age','model_ready','path_prediction','permission','entry_allocation_fraction']:close(pd.to_numeric(d[c]),expected.loc[signal,c])
            decisions[cid,win]=d;close(f.fees,f.quantity*f.price*.001);assert (f.quantity%100==0).all();ff=f.copy();ff['day']=pd.to_datetime(ff.fill_time).dt.strftime('%Y-%m-%d');ff['qchange']=np.where(ff.side.eq('BUY'),ff.quantity,-ff.quantity);ff['cashchange']=-ff.qchange*ff.price-ff.fees;flow=ff.groupby('day')[['qchange','cashchange']].sum().reindex(days,fill_value=0);close(a.quantity-a.quantity_before,flow.qchange);close(a.cash-a.cash_before,flow.cashchange)
            assert f.order_id.is_unique and o.order_id.is_unique and set(f.order_id)==set(o.loc[o.status.eq('FILLED'),'order_id']);counts=metric(a,t)
            for k,v in counts.items():close(v,summary[k])
            close(f.fees.sum(),summary['fees']);gross=0.;local=[]
            for cycle,cf in ff.groupby('cycle_id',sort=False):
                tr=t[t.cycle_id.eq(cycle)];assert len(tr)==1;cf=cf.sort_values('fill_time');assert cf.side.iloc[0]=='BUY';ending=int(cf.qchange.sum());assert ending>=0
                if tr.status.iloc[0]=='CLOSED':assert ending==0 and cf.side.iloc[-1]=='SELL'
                cycle_gross=float((-cf.qchange*cf.price).sum()+ending*a.close.iloc[-1]);gross+=cycle_gross
                dd=d[d.entry_cycle_after.map(lambda z:json.loads(z)['cycle_id'] if json.loads(z) else None).eq(cycle)];assert len(dd)>0;state=json.loads(dd.entry_cycle_after.iloc[0]);budget=Decimal(state['cash_budget']);cost=sum(Decimal(str(r.quantity))*Decimal(str(r.price))+Decimal(str(r.fees)) for r in cf[cf.side.eq('BUY')].itertuples());assert cost<=budget+Decimal('0.0000001');assert int(cf.loc[cf.side.eq('BUY'),'quantity'].sum())<=state['target_quantity']
                for encoded in dd.entry_cycle_after:
                    s=json.loads(encoded)
                    for field in ('cycle_id','opening_signal_identity','allocation_fraction','cash_budget','target_quantity'):assert s[field]==state[field]
                buyorders=o[o.cycle_id.eq(cycle)&o.side.eq('BUY')];entryday=cf.day.iloc[0];first=cf[cf.day.eq(entryday)];entrygross=float((first.qchange*(rawidx.loc[pd.Timestamp(entryday),'Close']-first.price)).sum());item={'candidate':cid,'window':win,'cycle':cycle,'status':tr.status.iloc[0],'cash_budget':str(budget),'actual_buy_cost_including_fees':str(cost),'locked_quantity':state['target_quantity'],'buy_fills':int(cf.side.eq('BUY').sum()),'buy_attempts':len(buyorders),'gross_yuan':cycle_gross,'fees_yuan':float(cf.fees.sum()),'net_yuan':cycle_gross-float(cf.fees.sum()),'entry_day_gross_yuan':entrygross,'later_gross_yuan':cycle_gross-entrygross};local.append(item);cycles.append(item)
            close(gross-float(f.fees.sum()),float(a.equity.iloc[-1]-100000));benchmark=pd.DataFrame(run['buyhold']['account_daily']['data']);bv=np.r_[100000.,benchmark.equity];close(float(np.max(1-bv/np.maximum.accumulate(bv))),summary['benchmark_dd']);close((bv[-1]/100000)**(252/len(a))-1,summary['benchmark_cagr'])
            if win=='full':
                gates={'return':counts['cagr']>=1.5*summary['benchmark_cagr'] if summary['benchmark_cagr']>0 else counts['cagr']>0,'relative_drawdown':counts['dd']<=.8*summary['benchmark_dd'],'absolute_drawdown':counts['dd']<=.25,'frequency_median':counts['frequency_median']>=6,'frequency_coverage':counts['frequency_good']>=338};assert gates==summary['checks'] and all(gates.values())==summary['center_pass']
            else:assert (counts['net_return']>.9158029150000013)==summary['return_superior'] and (counts['dd']<.07248663749114126)==summary['dd_superior']
            accounts.append({'candidate':cid,'parameters':p,'window':win,**counts,'gross_yuan':gross,'fees_yuan':float(f.fees.sum()),'net_yuan':float(a.equity.iloc[-1]-100000),'entry_day_gross_yuan':sum(v['entry_day_gross_yuan'] for v in local),'later_gross_yuan':sum(v['later_gross_yuan'] for v in local),'orders':len(o),'fills':len(f),'cycles':len(local),'ledger_reconciliation':'PASS','feature_prediction_intention_rows':len(d)})
        full=decisions[cid,'full'].set_index('signal_date');common=decisions[cid,'s011_common'].set_index('signal_date')
        for c in cols+['target_position','intent_age','path_prediction','permission','entry_allocation_fraction']:pd.testing.assert_series_equal(full.loc[common.index,c],common[c])
    serial=refread(read(OUT/'serial_preflight_ref.json'));first=refread(results['rows'][0]['evidence'])
    for left,right in zip(serial['runs'],first['runs'],strict=True):
        for k in ('account_daily','decisions','orders','fills','trades'):
            pd.testing.assert_frame_equal(pd.DataFrame(left['ledgers'][k]['data']),pd.DataFrame(right['ledgers'][k]['data']))
    result={'status':'PASS','accounts':accounts,'input_checks':input_checks,'input_checks_count':len(input_checks),'unique_bound_input_fetches':len(seen),'formal_ledger_exports_checked':csvchecks,'feature_prediction_intention_rows':sum(v['feature_prediction_intention_rows'] for v in accounts),'canonical_window_equivalence':'PASS','se_replay_audits':se,'serial_parallel_five_ledgers':'PASS','entry_cycle_semantics':'Signal-owned allocation; initial cash budget including fees and quantity remain fixed, retries consume remaining budget; independent SE audit verifies exact adoption, cost, exit and release facts.','limitations':['Seen development sample and historical share availability assumption.','Entry-day/later gross attribution is accounting, not identifiable avoided loss or causal component gain.'],'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    if any(v['status']!='PASS' for v in se):result['status']='PLATFORM_REPLAY_AUDIT_FAILED';result['independent_ledger_input_signal_audit']='PASS'
    (OUT/'account_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');pd.DataFrame(cycles).to_csv(OUT/'audit_cycle_details.csv',index=False);print(json.dumps({'status':result['status'],'accounts':len(accounts),'rows':result['feature_prediction_intention_rows'],'csv_tables':csvchecks,'SE_audits':len(se)},ensure_ascii=False))
if __name__=='__main__':main()
