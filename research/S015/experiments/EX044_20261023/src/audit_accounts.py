"""Read-only independent audit of existing EX044 public accounts and closures."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import StrategyCandidate, StrategyInputBinding, implementation_sha256

ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];OUT=HERE/'others';BASE=HERE.parent
COLS=['r1','r5','vol20','range20','pressure','return_time_balance','extrema_order','excursion_balance','halfday_balance','range_expansion','prior_range_compression','shock_concentration','gap_energy_share']
def read(p):return json.loads(p.read_bytes())
def close(a,b):np.testing.assert_allclose(a,b,atol=1e-8,rtol=1e-10)
def frame(v):return pd.DataFrame(v['data'])
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def normalize(f):
    f=f.copy();f.attrs={};f['Date']=pd.to_datetime(f.Date);return f.set_index('Date').sort_index()
def refread(v):return read(EvidenceRef.from_dict(v).resolve(ROOT))

def expected_decisions(features,params):
    rows=[];age=0
    for day,x in features.iterrows():
        models=[v for v in params['schedule'] if v['date']<=day]
        ready=bool(models) and day!='2024-12-31';path=risk=threshold=0.
        if ready:
            latest=models[-1];assert latest['train_known_max']<latest['date']<=day
            ps={}
            for role,m in latest['models'].items():
                ps[role]=float(m['beta'][0]+sum((float(x[c])-m['center'][i])/m['scale'][i]*m['beta'][i+1] for i,c in enumerate(m['columns'])))
            path,risk=ps['path'],ps['risk'];threshold=latest['models']['risk']['threshold']
        permit=ready and {'path':path>=0,'risk':risk<=threshold,'and':path>=0 and risk<=threshold}[params['mode']]
        if age>=params['hold']:age=0
        elif age:age+=1
        elif permit:age=1
        rows.append({'signal_date':day,**x.to_dict(),'target_position':float(age>0),'intent_age':age,'model_ready':float(ready),'path_prediction':path,'risk_prediction':risk,'risk_threshold':threshold,'permission':float(permit)})
    return pd.DataFrame(rows).set_index('signal_date')

def metric(a,t):
    eq=[100000.]+a.equity.astype(float).tolist();peak=100000.;dd=0.
    for value in eq:peak=max(peak,value);dd=max(dd,1-value/peak)
    dates=pd.to_datetime(a.date).dt.strftime('%Y-%m-%d').tolist()
    exits=pd.to_datetime(t.loc[t.status.eq('CLOSED'),'exit_date']).dt.strftime('%Y-%m-%d').tolist()
    counts=[sum(d in set(dates[i-59:i+1]) for d in exits) for i in range(59,len(dates))]
    return {'net_return':eq[-1]/100000.-1,'cagr':(eq[-1]/100000.)**(252/len(a))-1,'dd':dd,'closed':len(exits),'frequency_median':float(np.median(counts)),'frequency_good':sum(v>=3 for v in counts),'frequency_windows':len(counts)}

def frequency_bound(accounts):
    """A combinatorial bound for this fixed binary non-overlapping cycle only."""
    observed=[]
    for item in accounts:
        cid,win=item['candidate'],item['window'];hold=item['parameters']['hold']
        a=pd.read_csv(OUT/f'{cid}_{win}_account_daily.csv')
        t=pd.read_csv(OUT/f'{cid}_{win}_trades.csv');d=pd.read_csv(OUT/f'{cid}_{win}_decisions.csv')
        dayidx={x:i for i,x in enumerate(pd.to_datetime(a.date).dt.strftime('%Y-%m-%d'))}
        exits=[dayidx[x] for x in pd.to_datetime(t.loc[t.status.eq('CLOSED'),'exit_date']).dt.strftime('%Y-%m-%d')]
        gaps=np.diff(exits)
        assert (gaps>=hold+1).all()
        # Each complete positive intention run has exactly H decisions. It is
        # followed by a cash intention; account fills never shorten that clock.
        lengths=[];run=0
        for target in d.target_position:
            if target:run+=1
            elif run:lengths.append(run);run=0
        assert all(n==hold for n in lengths)
        observed.append({'candidate':cid,'window':win,'hold':hold,'closed':len(exits),'minimum_closed_exit_spacing':int(gaps.min()) if len(gaps) else None,'complete_positive_intention_runs':len(lengths),'all_complete_run_lengths_equal_hold':True,'trailing_open_intention_length':run,'sell_delay_sessions':0})
    # Supplement the proof with deterministic extremal phases and random
    # admissible spacings. These are date-count calculations, not accounts.
    cases=0;observed_max=0;rng=np.random.default_rng(13)
    for h in (10,11,12,20,60):
        calendars=[list(range(phase,434,h+1)) for phase in range(h+1)]
        for _ in range(100):
            xs=[];x=int(rng.integers(0,h+1))
            while x<434:xs.append(x);x+=h+1+int(rng.integers(0,6))
            calendars.append(xs)
        for xs in calendars:
            counts=[sum(start<=x<start+60 for x in xs) for start in range(375)]
            n6=sum(c>=6 for c in counts)
            if h==10:
                assert len(xs)<=40 and n6<=5*max(len(xs)-5,0)<=175
                observed_max=max(observed_max,n6)
            else:assert n6==0
            assert float(np.median(counts))<6
            cases+=1
    result={
        'status':'PROVEN_FOR_DECLARED_FIXED_CYCLE',
        'question':'Can a fixed hold H >= 10 in this exact single-position cycle satisfy the original 434-session median closed-trade frequency >= 6?',
        'answer':'No. The 60-session rolling CLOSED-count median is at most 5 under the stated execution and intention invariants.',
        'constants':{'sessions':434,'rolling_window':60,'rolling_windows':375,'windows_with_at_least_six_needed_for_median_six':188},
        'assumptions':[
            'One long-only instrument, one non-overlapping account cycle; CLOSED counts an entire position reaching zero, not partial sells or additional buys.',
            'Every entry intention starts H consecutive positive target decisions, then at least one zero target decision; no same-decision reentry and no early exit.',
            'T+1 execution follows binary available_cash_fraction/entry_cycle: positive targets can only buy/hold, zero targets can only sell/hold; no simultaneous exit and new entry.',
            'No forced end-window liquidation, external exit, overlapping subpositions, or intraday multi-round trips. Initial position is zero.',
            'Entry failures may shorten realized holding duration but do not reset the H-decision clock. Failed exits can postpone or merge cycles, never create an extra closed cycle during a positive target run.'
        ],
        'spacing_argument':'Two successive completed cycles require distinct positive intention runs. Between a close in the earlier zero-target run and the next close there are at least H positive-target execution sessions and the next zero-target execution session. Therefore successive CLOSED exit session indices differ by at least H+1. Later buy fills, buy retries and delayed sells cannot increase cycle density under these invariants.',
        'H10_proof':{
            'minimum_exit_spacing':11,
            'closed_count_upper_bound':40,
            'count_argument':'On indices 0..433, N <= floor(433/11)+1 = 40, even permitting an unrealistically early first close.',
            'six_exit_span_lower_bound':55,
            'windows_per_consecutive_six_block_upper_bound':5,
            'window_argument':'For six consecutive exits e1..e6, e6-e1 >= 55. A length-60 window start s containing them satisfies e6-59 <= s <= e1, allowing at most 60-(e6-e1) <= 5 integer starts.',
            'windows_with_at_least_six_upper_bound':175,
            'union_argument':'Every window with >=6 exits contains a consecutive six-exit block. There are at most N-5 such blocks, so the union has at most 5*(N-5) <= 175 windows. This is below 188 required for the median to reach 6.',
            'median_upper_bound':5},
        'H_ge_11_proof':{'six_exit_span_lower_bound':60,'maximum_span_inside_60_session_window':59,'windows_with_at_least_six_upper_bound':0,'median_upper_bound':5},
        'observed_EX044_execution_checks':observed,
        'synthetic_calendar_checks':{'cases':cases,'seed':13,'maximum_H10_windows_ge_six_seen':observed_max,'role':'Sanity checks supporting the algebraic proof, not exhaustive strategy backtests.'},
        'scope_limit':'This excludes only H>=10 for the stated fixed binary single-cycle construction. It does not exclude holding rules with early exits, variable holding, separate concurrent subpositions, different frequency counting, or another execution model. It does not assert that H<=9 will satisfy frequency or economics. No new economic gate is introduced.'}
    (OUT/'frequency_bound.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def main():
    source_home=BASE/'EX042_20261023'
    refs=read(source_home/'others/account_refs.json')
    for key,v in refs.items():assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes()==(source_home/key).read_bytes()
    successor_refs=read(OUT/'protocol_refs.json')
    for key,v in successor_refs.items():assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes()==(HERE/key).read_bytes()
    proto=refread(successor_refs['protocols/accounts.json']);schedules={k:refread(refs[f'others/models_{k}.json']) for k in ('A','B')}
    r=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/protocol_refs.json')['study.py'])
    oldpath=BASE/'EX026_20261023/src/study.py';assert oldpath.read_bytes()==r.resolve(ROOT).read_bytes()
    old=module(oldpath,'audited_old_input_loader');adj,raw,bars,rules,ids=old.inputs(old.sources())
    for f in (adj,raw,bars):f.attrs={}
    originals={'market':normalize(adj),'execution':normalize(raw),'intraday':normalize(bars)}
    rawidx=originals['execution'];dayseq=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').tolist();daypos={d:i for i,d in enumerate(dayseq)}
    fr=EvidenceRef.from_dict(read(BASE/'EX036_20261023/others/published_refs.json')['materials']['others/model_features.csv'])
    feature=pd.read_csv(fr.resolve(ROOT)).set_index('date')[COLS]
    feature=pd.concat([pd.DataFrame([{c:0. for c in COLS}],index=['2024-12-31']),feature])
    results=read(OUT/'results.json');assert len(results['rows'])==3 and results['account_scenarios']==6
    assert not results['precheck_five_ledgers_equal'] and results['technical_precheck_extra_scenarios']==0
    ctx=old.context();input_checks=[];seen={};accounts=[];cycle_rows=[];actual_decisions={};checked_csv=0
    source=source_home/'src/strategy_runtime';files=['strategies/price_information.py']
    for i,row in enumerate(results['rows']):
        cid=row['candidate_id'];assert row['parameters']==proto['configurations'][i]
        params={**row['parameters'],'schedule':schedules[row['parameters']['family']]}
        assert sha256(json.dumps(params['schedule'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==row['schedule_sha256']
        candidate=StrategyCandidate('S015',cid,{'decision_feedback':'MARKET_INTENT','parameters':params,'runtime':{'module':'strategy_runtime.strategies.price_information','qualname':'PriceInformation','contract_version':2,'source_files':files,'source_sha256':implementation_sha256(files,source_root=source)}},source)
        ev=refread(row['evidence']);assert candidate.runtime_identity_sha256==ev['strategy_identity']
        req=ev['request_identity'];assert req['initial_cash']==100000 and req['price_basis']=='HFQ_RESEARCH' and req['market_rules']==rules
        assert req['input_bindings']==ev['input_bindings']
        expected=expected_decisions(feature,params)
        for win,b in ev['input_bindings'].items():
            binding=StrategyInputBinding.from_mapping(b)
            assert b['plan']['calculation_dates'][0]=='2024-12-31' and b['plan']['calculation_dates'][-1]=='2026-10-20'
            for name in originals:
                rqt=binding.plan.requests[name];key=(str(binding.prepared.preparation_id),name,rqt.start,rqt.end)
                if key not in seen:
                    result=ctx.data.fetch(rqt,prepared=binding.prepared);assert result.ready,result.error
                    actual=normalize(result.dataframe)
                    want=originals[name].loc[rqt.start:rqt.end]
                    pd.testing.assert_index_equal(actual.index,want.index)
                    assert list(actual.columns)==list(want.columns)
                    differing={}
                    for col in actual:
                        mask=actual[col].ne(want[col])
                        if mask.any():
                            delta=actual[col]-want[col]
                            differing[col]={'rows':int(mask.sum()),'max_absolute':float(delta.abs().max()),'max_relative':float((delta.abs()/want[col].abs().replace(0,np.nan)).max()),'actual_dtype':str(actual[col].dtype),'prior_dtype':str(want[col].dtype)}
                    # Full equality remains required for daily inputs. Intraday
                    # Volume is unused by every feature and execution capacity.
                    if differing:
                        assert name=='intraday' and set(differing)=={'Volume'}
                    used=[c for c in actual.columns if name!='intraday' or c!='Volume']
                    pd.testing.assert_frame_equal(actual[used],want[used],check_dtype=False,check_exact=True)
                    seen[key]={'name':name,'rows':len(actual),'start':rqt.start,'end':rqt.end,'identity':result.identity.content_sha256,'exact_consumed_fields_overlap':'PASS','all_fields_exact':not differing,'unused_field_differences':differing,'field_dtypes':{c:{'actual':str(actual[c].dtype),'prior':str(want[c].dtype)} for c in actual}}
                input_checks.append({'candidate':cid,'window':win,**seen[key]})
        for run in ev['runs']:
            win=run['window_id'];summary=row['runs'][win];tables={k:frame(v) for k,v in run['ledgers'].items()}
            assert run['signal_support']['input_binding']==ev['input_bindings'][win]
            policy=run['signal_support']['execution_policy']['settings']['capital']
            assert policy=={'fee_rate':.001,'mode':'available_cash_fraction','target_scope':'entry_cycle','allocation_fraction':params['exposure']}
            for name,table in tables.items():
                exported=pd.read_csv(OUT/f'{cid}_{win}_{name}.csv')
                assert set(exported.columns)==set(table.columns) and len(exported)==len(table)
                for c in table:
                    if pd.api.types.is_numeric_dtype(table[c]):close(exported[c],table[c])
                    elif c in ('date','signal_date','valid_session','execution_date','fill_time','entry_date','exit_date','valuation_source_date'):
                        pd.testing.assert_series_equal(pd.to_datetime(exported[c]).astype('datetime64[ns]'),pd.to_datetime(table[c]).astype('datetime64[ns]'),check_names=False)
                    else:assert exported[c].fillna('').astype(str).tolist()==table[c].fillna('').astype(str).tolist(),c
                checked_csv+=1
            a,d,f,o,t=(tables[k] for k in ('account_daily','decisions','fills','orders','trades'))
            assert len(a)==(434 if win=='full' else 415) and len(a)==len(d)
            days=pd.to_datetime(a.date).dt.strftime('%Y-%m-%d');signal=pd.to_datetime(d.signal_date).dt.strftime('%Y-%m-%d')
            assert float(a.cash_before.iloc[0])==100000 and int(a.quantity_before.iloc[0])==0
            assert (pd.to_datetime(d.signal_date)<pd.to_datetime(d.valid_session)).all()
            close(a.equity,a.cash+a.quantity*a.close);close(a.cash_before.iloc[1:],a.cash.iloc[:-1]);close(a.quantity_before.iloc[1:],a.quantity.iloc[:-1])
            close(a.close,rawidx.loc[pd.to_datetime(a.date),'Close'])
            close(f.fees,f.quantity*f.price*.001);assert (f.quantity%100==0).all() and (f.quantity<=1000000).all()
            for c in COLS+['target_position','intent_age','model_ready','path_prediction','risk_prediction','risk_threshold','permission']:
                close(d[c],expected.loc[signal,c])
            assert d.target_position.isin([0.,1.]).all();actual_decisions[(cid,win)]=d
            ff=f.copy();ff['day']=pd.to_datetime(ff.fill_time).dt.strftime('%Y-%m-%d')
            ff['qchange']=np.where(ff.side.eq('BUY'),ff.quantity,-ff.quantity);ff['cashchange']=-ff.qchange*ff.price-ff.fees
            flow=ff.groupby('day')[['qchange','cashchange']].sum().reindex(days,fill_value=0)
            close(a.quantity-a.quantity_before,flow.qchange);close(a.cash-a.cash_before,flow.cashchange)
            assert set(f.order_id)==set(o.loc[o.status.eq('FILLED'),'order_id'])
            assert f.order_id.is_unique and o.order_id.is_unique
            quotes=rawidx.loc[pd.to_datetime(ff.day)]
            assert (ff.price.to_numpy()>=quotes.Low.to_numpy()-1e-10).all() and (ff.price.to_numpy()<=quotes.High.to_numpy()+1e-10).all()
            merged=ff.merge(d[['decision_id','intent_age','target_position']],on='decision_id',validate='many_to_one')
            held=a[['quantity_before']].copy();held['day']=days
            merged=merged.merge(held,on='day',validate='many_to_one');assert len(merged)==len(ff)
            additional=merged[(merged.quantity_before>0)&merged.side.eq('BUY')]
            partial=merged[(merged.quantity_before>0)&merged.side.eq('SELL')&(merged.target_position>0)]
            counts=metric(a,t)
            for k,v in counts.items():close(v,summary[k])
            close(f.fees.sum(),summary['fees'])
            benchmark=frame(run['buyhold']['account_daily']);bv=np.r_[100000.,benchmark.equity]
            close(float(np.max(1-bv/np.maximum.accumulate(bv))),summary['benchmark_dd'])
            close((bv[-1]/100000.)**(252/len(a))-1,summary['benchmark_cagr'])
            if win=='full':
                gates={'return':counts['cagr']>=1.5*summary['benchmark_cagr'] if summary['benchmark_cagr']>0 else counts['cagr']>0,'relative_drawdown':counts['dd']<=.8*summary['benchmark_dd'],'absolute_drawdown':counts['dd']<=.25,'frequency_median':counts['frequency_median']>=6,'frequency_coverage':counts['frequency_good']>=338}
                assert gates==summary['checks'] and all(gates.values())==summary['center_pass']
            else:
                assert (counts['net_return']>.9158029150000013)==summary['return_superior'] and (counts['dd']<.07248663749114126)==summary['dd_superior']
            local=[]
            for cycle,cf in ff.groupby('cycle_id',sort=False):
                cf=cf.sort_values('fill_time');tr=t[t.cycle_id.eq(cycle)];assert len(tr)==1
                status=tr.status.iloc[0];entry=cf.iloc[0];assert entry.side=='BUY'
                ending=int(cf.qchange.sum());assert ending>=0
                if status=='CLOSED':assert ending==0 and cf.iloc[-1].side=='SELL'
                gross=float((-cf.qchange*cf.price).sum()+ending*a.close.iloc[-1]);fees=float(cf.fees.sum())
                entryday=cf[cf.day.eq(entry.day)];entrygross=float((entryday.qchange*(rawidx.loc[pd.Timestamp(entry.day),'Close']-entryday.price)).sum())
                endday=pd.Timestamp(tr.exit_date.iloc[0]).strftime('%Y-%m-%d') if status=='CLOSED' else days.iloc[-1]
                held_sessions=daypos[endday]-daypos[entry.day]
                initial_age=int(d.loc[d.decision_id.eq(entry.decision_id),'intent_age'].iloc[0])
                co=o[o.cycle_id.eq(cycle)];buys=co[co.side.eq('BUY')]
                locked_quantity=int(buys.sort_values('execution_date').quantity.iloc[0])
                assert int(cf.loc[cf.side.eq('BUY'),'quantity'].sum())<=locked_quantity
                exit_delay=None
                if status=='CLOSED':
                    first_sell_day=pd.Timestamp(co[co.side.eq('SELL')].sort_values('execution_date').execution_date.iloc[0]).strftime('%Y-%m-%d')
                    exit_delay=daypos[endday]-daypos[first_sell_day]
                    assert exit_delay>=0 and held_sessions+initial_age-1==params['hold']+exit_delay
                v={'candidate':cid,'window':win,'cycle':cycle,'status':status,'entry_day':entry.day,'last_day':endday,'holding_session_gap':held_sessions,'entry_intent_age':initial_age,'entry_delay_sessions':initial_age-1,'buy_attempts':len(buys),'buy_retry_orders':max(len(buys)-1,0),'buy_fills':int(cf.side.eq('BUY').sum()),'sell_fills':int(cf.side.eq('SELL').sum()),'gross_yuan':gross,'fees_yuan':fees,'net_yuan':gross-fees,'entry_day_gross_yuan':entrygross,'later_gross_yuan':gross-entrygross}
                v['locked_cycle_quantity']=locked_quantity;v['exit_delay_sessions']=exit_delay
                local.append(v);cycle_rows.append(v)
            assert set(f.cycle_id)==set(t.cycle_id)
            gross=sum(z['gross_yuan'] for z in local);fees=float(f.fees.sum())
            close(gross-fees,float(a.equity.iloc[-1]-100000))
            buyorders=o[o.side.eq('BUY')];buyattempts=buyorders.groupby('cycle_id').size()
            closed_details=[z for z in local if z['status']=='CLOSED']
            hist={str(k):sum(z['holding_session_gap']==k for z in closed_details) for k in sorted({z['holding_session_gap'] for z in closed_details})}
            accounts.append({'candidate':cid,'parameters':row['parameters'],'window':win,**counts,'gross_yuan':gross,'fees_yuan':fees,'net_yuan':float(a.equity.iloc[-1]-100000),'ending_quantity':int(a.quantity.iloc[-1]),'open_cycles':int(t.status.eq('OPEN').sum()),'orders':len(o),'fills':len(f),'additional_buy_fills':len(additional),'partial_sell_fills':len(partial),'buy_retry_orders':int((buyattempts-1).clip(lower=0).sum()),'unfilled_buy_orders':int((~buyorders.status.eq('FILLED')).sum()),'unfilled_buy_reasons':buyorders.loc[~buyorders.status.eq('FILLED'),'reason'].value_counts().to_dict(),'buy_order_cycles_without_fills':len(set(buyorders.cycle_id)-set(f.cycle_id)),'delayed_entry_cycles':sum(z['entry_delay_sessions']>0 for z in local),'closed_holding_session_gaps':hist,'entry_day_gross_yuan':sum(z['entry_day_gross_yuan'] for z in local),'later_gross_yuan':sum(z['later_gross_yuan'] for z in local),'ledger_reconciliation':'PASS','all_feature_prediction_intention_rows':len(d)})
        full=actual_decisions[(cid,'full')].set_index('signal_date');common=actual_decisions[(cid,'s011_common')].set_index('signal_date')
        for c in COLS+['target_position','intent_age','path_prediction','risk_prediction','risk_threshold','permission']:
            pd.testing.assert_series_equal(full.loc[common.index,c],common[c])
    out={'status':'PASS','scope':'Existing six EX044 formal accounts only. Frozen model schedules reconstructed into candidate runtime identity; independent scalar predictions from authenticated EX036 features, not mutable signal CSVs. No prepare/evaluate calls.','accounts':accounts,'input_checks':input_checks,'input_checks_count':len(input_checks),'formal_ledger_exports_checked':checked_csv,'feature_prediction_intention_rows':sum(v['all_feature_prediction_intention_rows'] for v in accounts),'canonical_window_equivalence':'PASS','historical_data_identities':ids,'entry_cycle_semantics':'Binary intentions, locked requested cycle quantity; retry possible until intention closes. Actual holding lengths are measured, not asserted equal to hold. Open ending cycles marked at last close, never forced sold.','diagnostic_limits':'Gross profit is fixed realized fill cash flow plus terminal position mark before actual fees, not a rerun with zero fees. Entry-day/later split is ledger attribution, not avoidable loss or causal identification.','technical_precheck':'No additional precheck accounts in EX044; runtime execution path was checked by EX042 technical two-account reproduction.'}
    differences=[x for x in input_checks if not x['all_fields_exact']]
    (OUT/'input_difference_observed.json').write_text(json.dumps({'status':'DISCLOSED_UNUSED_FIELD_DIFFERENCE','differences':differences,'impact':'All 2547 actual feature/prediction/permission/intention rows match old certified features. Intraday Volume is unused; all used fields match exactly.'},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'account_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    pd.DataFrame(cycle_rows).to_csv(OUT/'audit_cycle_details.csv',index=False)
    frequency_bound(accounts)
    print(json.dumps({'status':'PASS','accounts':len(accounts),'rows':out['feature_prediction_intention_rows'],'inputs':len(input_checks),'csv_tables':checked_csv,'summaries':[{k:v[k] for k in ('candidate','window','gross_yuan','fees_yuan','net_yuan','additional_buy_fills','partial_sell_fills','buy_retry_orders','unfilled_buy_orders','closed_holding_session_gaps')} for v in accounts]},ensure_ascii=False))

if __name__=='__main__':main()
