"""Independent EX047 permission-exit finite-domain and account audit, no account reruns."""
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
        if age:
            expired=age>=params['hold']
            lost=not permit and params['exit_rule']=='permission'
            age=0 if expired or lost else age+1
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

def main():
    source_home=BASE/'EX042_20261023'
    refs=read(source_home/'others/account_refs.json')
    for key,v in refs.items():assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes()==(source_home/key).read_bytes()
    successor_refs=read(OUT/'protocol_refs.json')
    for key,v in successor_refs.items():assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes()==(HERE/key).read_bytes()
    proto=refread(successor_refs['protocols/accounts.json']);schedules={k:refread(refs[f'others/models_{k}.json']) for k in ('A','B')}
    declared={(p['family'],p['mode'],p['exit_rule'],p['hold']) for p in proto['configurations']}
    maxima={'A/path':16,'A/risk':18,'A/and':8,'B/path':22,'B/risk':24,'B/and':13}
    assert proto['maximum_permission_runs']==maxima
    permission={(fm.split('/')[0],fm.split('/')[1],'permission',h) for fm,bound in maxima.items() for h in range(10,bound+1)}-{('B','path','permission',15)}
    assert len(proto['configurations'])==len(declared)==47 and declared==permission
    assert all(p['exposure']==1. for p in proto['configurations'])
    r=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/protocol_refs.json')['study.py'])
    oldpath=BASE/'EX026_20261023/src/study.py';assert oldpath.read_bytes()==r.resolve(ROOT).read_bytes()
    old=module(oldpath,'audited_old_input_loader');adj,raw,bars,rules,ids=old.inputs(old.sources())
    for f in (adj,raw,bars):f.attrs={}
    originals={'market':normalize(adj),'execution':normalize(raw),'intraday':normalize(bars)}
    rawidx=originals['execution'];dayseq=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').tolist();daypos={d:i for i,d in enumerate(dayseq)}
    fr=EvidenceRef.from_dict(read(BASE/'EX036_20261023/others/published_refs.json')['materials']['others/model_features.csv'])
    feature=pd.read_csv(fr.resolve(ROOT)).set_index('date')[COLS]
    feature=pd.concat([pd.DataFrame([{c:0. for c in COLS}],index=['2024-12-31']),feature])
    independently_observed_maxima={}
    for family in ('A','B'):
        for mode in ('path','risk','and'):
            observed=expected_decisions(feature,{'family':family,'mode':mode,'hold':434,'exposure':1.,'exit_rule':'permission','schedule':schedules[family]})
            run=maxrun=0
            for permitted in observed.permission:
                run=run+1 if permitted else 0;maxrun=max(maxrun,run)
            independently_observed_maxima[family+'/'+mode]=maxrun
    assert independently_observed_maxima==maxima
    results=read(OUT/'results.json');assert len(results['rows'])==len(proto['configurations']) and results['account_scenarios']==2*len(results['rows'])
    assert len({row['candidate_id'] for row in results['rows']})==len(results['rows'])
    assert not results['precheck_five_ledgers_equal'] and results['technical_precheck_extra_scenarios']==0
    ctx=old.context();input_checks=[];seen={};accounts=[];cycle_rows=[];actual_decisions={};checked_csv=0
    source=BASE/'EX045_20261023/src/strategy_runtime';files=['strategies/price_information.py']
    runtime_refs=read(BASE/'EX045_20261023/others/protocol_refs.json')
    for key in ('src/strategy_runtime/strategies/price_information.py','others/runtime_checks.json'):
        assert EvidenceRef.from_dict(runtime_refs[key]).resolve(ROOT).read_bytes()==(BASE/'EX045_20261023'/key).read_bytes()
    runtime_checks=read(BASE/'EX045_20261023/others/runtime_checks.json');assert runtime_checks['status']=='PASS'
    assert sha256((source/files[0]).read_bytes()).hexdigest()==runtime_checks['source_sha256']
    assert EvidenceRef.from_dict(proto['source_ref']).resolve(ROOT).read_bytes()==(source/files[0]).read_bytes()
    for i,row in enumerate(results['rows']):
        cid=row['candidate_id'];assert row['parameters']==proto['configurations'][i]
        params={**row['parameters'],'schedule':schedules[row['parameters']['family']]}
        assert params['exit_rule']=='permission' and type(params['hold']) is int and params['hold']>=1
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
                exit_delay=None;exit_reason=None;exit_previous_intent_age=None
                if status=='CLOSED':
                    first_sell_day=pd.Timestamp(co[co.side.eq('SELL')].sort_values('execution_date').execution_date.iloc[0]).strftime('%Y-%m-%d')
                    exit_delay=daypos[endday]-daypos[first_sell_day]
                    assert exit_delay>=0
                    first_sell=co[co.side.eq('SELL')].sort_values('execution_date').iloc[0]
                    exit_decision=d.loc[d.decision_id.eq(first_sell.decision_id)].iloc[0]
                    exit_signal=pd.Timestamp(exit_decision.signal_date).strftime('%Y-%m-%d')
                    j=expected.index.get_loc(exit_signal);assert j>0
                    exit_previous_intent_age=int(expected.intent_age.iloc[j-1])
                    assert 1<=exit_previous_intent_age<=params['hold']
                    assert float(exit_decision.target_position)==0. and int(exit_decision.intent_age)==0
                    assert held_sessions+initial_age-1==exit_previous_intent_age+exit_delay
                    assert held_sessions+initial_age-1<=params['hold']+exit_delay
                    exit_reason='maximum_age' if exit_previous_intent_age>=params['hold'] else 'permission_lost'
                    if params['exit_rule']=='fixed':assert exit_previous_intent_age==params['hold'] and exit_reason=='maximum_age'
                    elif exit_reason=='permission_lost':assert not bool(exit_decision.permission)
                v={'candidate':cid,'window':win,'cycle':cycle,'status':status,'entry_day':entry.day,'last_day':endday,'holding_session_gap':held_sessions,'entry_intent_age':initial_age,'entry_delay_sessions':initial_age-1,'buy_attempts':len(buys),'buy_retry_orders':max(len(buys)-1,0),'buy_fills':int(cf.side.eq('BUY').sum()),'sell_fills':int(cf.side.eq('SELL').sum()),'gross_yuan':gross,'fees_yuan':fees,'net_yuan':gross-fees,'entry_day_gross_yuan':entrygross,'later_gross_yuan':gross-entrygross}
                v['locked_cycle_quantity']=locked_quantity;v['exit_delay_sessions']=exit_delay
                v['exit_reason']=exit_reason;v['exit_previous_intent_age']=exit_previous_intent_age
                local.append(v);cycle_rows.append(v)
            assert set(f.cycle_id)==set(t.cycle_id)
            gross=sum(z['gross_yuan'] for z in local);fees=float(f.fees.sum())
            close(gross-fees,float(a.equity.iloc[-1]-100000))
            buyorders=o[o.side.eq('BUY')];buyattempts=buyorders.groupby('cycle_id').size()
            closed_details=[z for z in local if z['status']=='CLOSED']
            hist={str(k):sum(z['holding_session_gap']==k for z in closed_details) for k in sorted({z['holding_session_gap'] for z in closed_details})}
            accounts.append({'candidate':cid,'parameters':row['parameters'],'window':win,**counts,'gross_yuan':gross,'fees_yuan':fees,'net_yuan':float(a.equity.iloc[-1]-100000),'ending_quantity':int(a.quantity.iloc[-1]),'open_cycles':int(t.status.eq('OPEN').sum()),'orders':len(o),'fills':len(f),'additional_buy_fills':len(additional),'partial_sell_fills':len(partial),'buy_retry_orders':int((buyattempts-1).clip(lower=0).sum()),'unfilled_buy_orders':int((~buyorders.status.eq('FILLED')).sum()),'unfilled_buy_reasons':buyorders.loc[~buyorders.status.eq('FILLED'),'reason'].value_counts().to_dict(),'buy_order_cycles_without_fills':len(set(buyorders.cycle_id)-set(f.cycle_id)),'delayed_entry_cycles':sum(z['entry_delay_sessions']>0 for z in local),'closed_holding_session_gaps':hist,'exit_reasons':{reason:sum(z['exit_reason']==reason for z in closed_details) for reason in ('maximum_age','permission_lost')},'entry_day_gross_yuan':sum(z['entry_day_gross_yuan'] for z in local),'later_gross_yuan':sum(z['later_gross_yuan'] for z in local),'ledger_reconciliation':'PASS','all_feature_prediction_intention_rows':len(d)})
        full=actual_decisions[(cid,'full')].set_index('signal_date');common=actual_decisions[(cid,'s011_common')].set_index('signal_date')
        for c in COLS+['target_position','intent_age','path_prediction','risk_prediction','risk_threshold','permission']:
            pd.testing.assert_series_equal(full.loc[common.index,c],common[c])
    out={'status':'PASS','scope':'All existing EX047 formal accounts only. Frozen model schedules reconstructed into candidate runtime identity; independent scalar predictions from authenticated EX036 features, not mutable signal CSVs. No prepare/evaluate calls.','accounts':accounts,'input_checks':input_checks,'input_checks_count':len(input_checks),'formal_ledger_exports_checked':checked_csv,'feature_prediction_intention_rows':sum(v['all_feature_prediction_intention_rows'] for v in accounts),'canonical_window_equivalence':'PASS','historical_data_identities':ids,'entry_cycle_semantics':'Binary intentions, locked requested cycle quantity; retry possible until intention closes. Actual holding lengths are measured, not asserted equal to hold. Open ending cycles marked at last close, never forced sold.','diagnostic_limits':'Gross profit is fixed realized fill cash flow plus terminal position mark before actual fees, not a rerun with zero fees. Entry-day/later split is ledger attribution, not avoidable loss or causal identification.','technical_precheck':'EX047 has zero technical repeat scenarios. Exact EX045 source reuse is authenticated; previous EX045 runner serial/parallel equality is historical supporting evidence only. No audit account reruns.'}
    differences=[x for x in input_checks if not x['all_fields_exact']]
    (OUT/'input_difference_observed.json').write_text(json.dumps({'status':'DISCLOSED_UNUSED_FIELD_DIFFERENCE','differences':differences,'impact':f"All {out['feature_prediction_intention_rows']} actual feature/prediction/permission/intention rows match independently rebuilt permission-exit decisions from certified features. Intraday Volume is unused; all used fields match exactly."},ensure_ascii=False,indent=2),encoding='utf-8')
    out['audit_source_sha256']=sha256(Path(__file__).read_bytes()).hexdigest()
    out['maximum_permission_runs_recomputed']=independently_observed_maxima
    out['permission_exit_semantics']='Closed cycle duration plus entry delay equals preceding intent age plus market-sell delay; preceding intent age never exceeds cap. Fixed cycles exit exactly at cap; every permission pre-cap exit has false current permission.'
    (OUT/'account_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    pd.DataFrame(cycle_rows).to_csv(OUT/'audit_cycle_details.csv',index=False)
    print(json.dumps({'status':'PASS','accounts':len(accounts),'rows':out['feature_prediction_intention_rows'],'inputs':len(input_checks),'csv_tables':checked_csv,'summaries':[{k:v[k] for k in ('candidate','window','gross_yuan','fees_yuan','net_yuan','additional_buy_fills','partial_sell_fills','buy_retry_orders','unfilled_buy_orders','closed_holding_session_gaps')} for v in accounts]},ensure_ascii=False))

def audit_summary():
    """Recompute the six-experiment summary without generating new accounts."""
    summary=read(OUT/'search_summary.json');rows=[];counts=[];checks=0
    for number in range(42,48):
        home=BASE/f'EX{number:03d}_20261023';result=read(home/'others/results.json');audit=read(home/'others/account_audit.json');assert audit['status']=='PASS'
        counts.append({'experiment':home.name,**{key:result[key] for key in ('new_configurations','account_scenarios','technical_precheck_extra_scenarios','qualified_centers')}})
        accounts={(x['candidate'],x['window']):x for x in audit['accounts']}
        assert len(accounts)==result['account_scenarios']==2*len(result['rows'])
        for row in result['rows']:
            r={**row,'experiment':home.name,'parameters':{**row['parameters'],'exit_rule':row['parameters'].get('exit_rule','fixed')}}
            for window,run in row['runs'].items():
                observed=accounts[row['candidate_id'],window]
                for key in ('net_return','cagr','dd','closed','frequency_median','frequency_good','frequency_windows'):close(run[key],observed[key]);checks+=1
            full,common=row['runs']['full'],row['runs']['s011_common'];assert row['both_center_pass']==(full['center_pass'] and common['return_superior'] and common['dd_superior'])
            # Both accounts start before the first trained model, so measured
            # equity paths thereafter have identical terminal economic values.
            close(full['net_return'],common['net_return']);close(full['dd'],common['dd'])
            rows.append(r)
    assert summary['counts']==counts
    identity=lambda r:(r['parameters']['family'],r['parameters']['mode'],r['parameters']['exit_rule'],r['parameters']['hold'])
    keys={identity(r) for r in rows};assert len(rows)==len(keys)==159
    maxima={'A/path':16,'A/risk':18,'A/and':8,'B/path':22,'B/risk':24,'B/and':13}
    fixed={(f,m,'fixed',h) for f in ('A','B') for m in ('path','risk','and') for h in range(1,10)}
    permission={(fm.split('/')[0],fm.split('/')[1],'permission',h) for fm,M in maxima.items() for h in range(1,M+1)}
    redundant={('A','and','permission',9),('B','path','permission',30),('B','and','permission',15),('B','and','permission',30)}
    assert keys==fixed|permission|redundant and len(fixed)==54 and len(permission)==101
    assert summary['finite_domain']['maximum_permission_runs']==maxima
    for key,value in [('fixed_representatives',54),('permission_representatives',101),('above_bound_redundant_identities',4)]:assert summary['finite_domain'][key]==value
    assert summary['total_configurations']==159 and summary['standard_accounts']==sum(c['account_scenarios'] for c in counts)==318
    assert summary['technical_repeat_accounts']==sum(c['technical_precheck_extra_scenarios'] for c in counts)==4
    for key,value in [('full_center_pass',sum(r['runs']['full']['center_pass'] for r in rows)),('common_return_pass',sum(r['runs']['s011_common']['return_superior'] for r in rows)),('common_dd_pass',sum(r['runs']['s011_common']['dd_superior'] for r in rows)),('joint_pass',sum(r['both_center_pass'] for r in rows))]:assert summary[key]==value
    def concise(r):
        f=r['runs']['full'];c=r['runs']['s011_common']
        return {'experiment':r['experiment'],'candidate':r['candidate_id'],'parameters':r['parameters'],'net_return':f['net_return'],'dd':f['dd'],'cagr':f['cagr'],'closed':f['closed'],'frequency_median':f['frequency_median'],'frequency_good':f['frequency_good'],'full_pass':f['center_pass'],'common_return_pass':c['return_superior'],'common_dd_pass':c['dd_superior'],'joint_pass':r['both_center_pass'],'evidence':r['evidence']}
    best=max(rows,key=lambda r:r['runs']['full']['net_return']);low=min(rows,key=lambda r:r['runs']['full']['dd'])
    assert summary['best_return']==concise(best) and summary['lowest_dd']==concise(low)
    frontier=[]
    for r in rows:
        ret,dd=r['runs']['full']['net_return'],r['runs']['full']['dd'];dominated=False
        for s in rows:
            sr,sd=s['runs']['full']['net_return'],s['runs']['full']['dd']
            if sr>=ret and sd<=dd and (sr>ret or sd<dd):dominated=True;break
        if not dominated:frontier.append(concise(r))
    assert summary['return_dd_frontier']==frontier
    for group in summary['family_summary']:
        rr=[r for r in rows if identity(r)[:3]==(group['family'],group['mode'],group['exit_rule'])]
        assert group['count']==len(rr) and group['best_return']==concise(max(rr,key=lambda r:r['runs']['full']['net_return'])) and group['lowest_dd']==concise(min(rr,key=lambda r:r['runs']['full']['dd']))
    expected_centers=[concise(r) for r in rows if r['runs']['full']['center_pass']];assert summary['full_center_candidates']==expected_centers
    selected={r['candidate_id']:r for r in rows if r['runs']['full']['center_pass']};selected.update({best['candidate_id']:best,low['candidate_id']:low})
    assert {s['candidate'] for s in summary['time_diagnostics']}==set(selected)
    def local_dd(values):
        peak=float(values[0]);worst=0.
        for v in values:peak=max(peak,float(v));worst=max(worst,1-float(v)/peak)
        return worst
    time_rows=0
    for item in summary['time_diagnostics']:
        row=selected[item['candidate']];home=BASE/row['experiment'];csv=home/f"others/{row['candidate_id']}_full_account_daily.csv";daily=pd.read_csv(csv,parse_dates=['date'])
        # The source ledger is independently authenticated even if EX047 has not
        # yet been published; this avoids trusting a mutable CSV alone.
        evidence=refread(row['evidence']);run=next(r for r in evidence['runs'] if r['window_id']=='full');original=frame(run['ledgers']['account_daily'])
        close(daily.equity,original.equity);assert pd.to_datetime(daily.date).tolist()==pd.to_datetime(original.date).tolist()
        capital=[100000.,*daily.equity.astype(float).tolist()];peaks=[];peak=100000.
        for value in capital:peak=max(peak,value);peaks.append(peak)
        for year in item['years']:
            indices=[i for i,date in enumerate(daily.date) if date.year==year['year']];first,last=indices[0],indices[-1];values=capital[first:last+2]
            assert year['sessions']==len(indices) and year['start']==daily.date.iloc[first].date().isoformat() and year['end']==daily.date.iloc[last].date().isoformat()
            close(year['return'],values[-1]/values[0]-1);close(year['local_peak_dd'],local_dd(values));close(year['inherited_peak_dd'],max(1-capital[i+1]/peaks[i+1] for i in indices));time_rows+=1
        starts=list(range(0,len(daily)-251,21));assert len(starts)==len(item['rolling252_step21'])
        for start,window in zip(starts,item['rolling252_step21']):
            values=capital[start:start+253];assert len(values)==253
            assert window['start']==daily.date.iloc[start].date().isoformat() and window['end']==daily.date.iloc[start+251].date().isoformat()
            close(window['return'],values[-1]/values[0]-1);close(window['local_peak_dd'],local_dd(values));time_rows+=1
    for name,value in summary['source_hashes'].items():assert sha256((BASE/name).read_bytes()).hexdigest()==value
    centers=pd.read_csv(OUT/'all_centers.csv');assert len(centers)==159
    for r in rows:
        z=centers.loc[centers.candidate.eq(r['candidate_id'])].iloc[0]
        assert z.experiment==r['experiment'] and bool(z.joint_pass)==r['both_center_pass']
        for k in ('net_return','dd','cagr','closed','frequency_median','frequency_good'):close(z[k],r['runs']['full'][k])
        close(z.common_return,r['runs']['s011_common']['net_return']);close(z.common_dd,r['runs']['s011_common']['dd'])
    delivery=(HERE/'src/deliver.py').read_text(encoding='utf-8')
    assert "assert summary['joint_pass']==0" in delivery and 'd.CandidateSet((),(),(*prior.searches,*searches)' in delivery
    receipt=read(ROOT/'research/S015/deliveries/CANDIDATES/4/receipt.json');prior_path=ROOT/'research/S015/assets/deliveries/CANDIDATES/4/delivery.json'
    assert sha256(prior_path.read_bytes()).hexdigest()==next(f['sha256'] for f in receipt['files'] if f['path']=='delivery.json')
    prior=read(prior_path)['content']['payload'];assert not prior['handoff']
    assets=[Path(__file__),HERE/'src/summarize.py',HERE/'src/deliver.py',OUT/'search_summary.json',OUT/'all_centers.csv']
    out={'status':'PASS','scope':'Independent arithmetic and source-ledger audit; not execution of final delivery.','configuration_identities':159,'finite_representatives':155,'above_bound_redundant_identities':4,'standard_accounts':318,'technical_repeat_accounts':4,'account_summary_values_checked':checks,'time_slices_recomputed':time_rows,'time_candidates':len(selected),'best_return_candidate':best['candidate_id'],'lowest_drawdown_candidate':low['candidate_id'],'joint_pass':summary['joint_pass'],'empty_handoff_allowed':summary['joint_pass']==0,'delivery_static_guard':'joint_pass==0 required; empty CandidateSet with prior searches preserved; no historical registry writes in delivery script','permission_bound_review':'Fixed hold-independent permission sequence; false resets age; on any true run L<=M, kth day begins with age k-1<M, so all caps>=M remain identical. Historical fixed-path statement only.','sha256':{str(p.relative_to(HERE)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in assets},'limitations':'Representative selection is descriptive and based on seen development results. Local and inherited drawdowns are separately labelled; no stage-four economic validation or final delivery mutation is performed by this audit.'}
    (OUT/'summary_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False))

if __name__=='__main__':
    import sys
    if '--summary-only' in sys.argv:audit_summary()
    else:main()
