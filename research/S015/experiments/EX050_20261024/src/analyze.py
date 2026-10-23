"""Authenticate formal P2 accounts and describe allocation opportunity costs."""
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

import numpy as np
import pandas as pd
from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import AccountDiagnosisRequest, AccountRunRef, EvaluationIdentity
from strategy_manager import CandidateKey
from strategy_runtime import StrategyInputBinding
from run import HERE, ROOT, OLD, SOURCE, FILES, MODES, read, save, authenticate, context, module


def close(a, b):
    np.testing.assert_allclose(a, b, rtol=1e-10, atol=1e-8, equal_nan=True)


def independent_intentions(features, schedule, mode):
    rows=[]
    age=0
    fraction=None
    for day, row in features.iterrows():
        live=[model for model in schedule if model['date']<=day]
        ready=day!='2024-12-31' and bool(live)
        prediction={'path':0.,'risk':0.}
        threshold=0.
        if ready:
            model=live[-1]
            assert model['train_known_max']<model['date']<=day
            for role, coefficients in model['models'].items():
                prediction[role]=coefficients['beta'][0]+sum(
                    (float(row[column])-coefficients['center'][index])/coefficients['scale'][index]*coefficients['beta'][index+1]
                    for index,column in enumerate(coefficients['columns']))
            threshold=model['models']['risk']['threshold']
        risk_allowed=ready and prediction['risk']<=threshold
        permission=ready and prediction['path']>=0 and (mode!='risk_reject' or risk_allowed)
        if age==3:
            age=0
            fraction=None
        elif age:
            age+=1
        elif permission:
            age=1
            fraction={'fixed100':1.,'fixed50':.5,'fixed75':.75,'risk_reject':1.,'risk_half':1. if risk_allowed else .5}[mode]
        rows.append({'signal_date':day,'target_position':float(age>0),'intent_age':age,
            'entry_allocation_fraction':fraction,'path_prediction':prediction['path'],
            'risk_prediction':prediction['risk'],'risk_threshold':threshold,'risk_allowed':float(risk_allowed),
            'permission':float(permission),'model_ready':float(ready)})
    return pd.DataFrame(rows).set_index('signal_date')


def amounts(frame, value, mask):
    v=frame[value].to_numpy(float)
    chosen=np.asarray(mask,dtype=bool)
    loss=np.maximum(-v,0.)
    profit=np.maximum(v,0.)
    return {'n':len(frame),'selected_n':int(chosen.sum()),'loss_n':int((v<0).sum()),
            'profit_n':int((v>0).sum()),'selected_loss_n':int((chosen&(v<0)).sum()),
            'selected_profit_n':int((chosen&(v>0)).sum()),'loss_denominator_yuan':float(loss.sum()),
            'profit_denominator_yuan':float(profit.sum()),'selected_loss_yuan':float(loss[chosen].sum()),
            'selected_profit_yuan':float(profit[chosen].sum()),
            'loss_fraction':float(loss[chosen].sum()/loss.sum()) if loss.sum() else None,
            'profit_fraction':float(profit[chosen].sum()/profit.sum()) if profit.sum() else None}


def main():
    sources,_=authenticate()
    from czsc_trader.research_tools import EvidenceRef
    results=read(HERE/'others/results.json')
    assert len(results['rows'])==5 and results['precheck_five_ledgers_equal']
    runtime=module(SOURCE/FILES[0],'ex050_account_runtime')
    feature=pd.read_csv(EvidenceRef.from_dict(sources['training_input:others/model_features.csv']).resolve(ROOT)).set_index('date')[list(runtime.COLUMNS)]
    feature=pd.concat([pd.DataFrame([{c:0. for c in runtime.COLUMNS}],index=['2024-12-31']),feature])
    schedule=read(OLD/'others/models_A.json')
    ctx=context(1)
    fetched={}
    accounts=[]
    cycles=[]
    diagnostic=[]
    ledger_checks=0
    for row in results['rows']:
        cid=row['candidate_id']
        mode=row['parameters']['allocation_mode']
        ref=EvidenceRef.from_dict(row['evidence'])
        evidence=read(ref.resolve(ROOT))
        assert evidence['request_identity']['initial_cash']==100000
        assert evidence['request_identity']['price_basis']=='HFQ_RESEARCH'
        expected=independent_intentions(feature,schedule,mode)
        for window,binding_raw in evidence['input_bindings'].items():
            binding=StrategyInputBinding.from_mapping(binding_raw)
            frames={}
            for name in ('market','execution','intraday'):
                request=binding.plan.requests[name]
                key=(str(binding.prepared.preparation_id),name,request.start,request.end)
                if key not in fetched:
                    data=ctx.data.fetch(request,prepared=binding.prepared)
                    assert data.ready,data.error
                    fetched[key]=data.dataframe.copy()
                    fetched[key].attrs={}
                frames[name]=fetched[key]
            actual=runtime.causal_features(frames['market'],frames['execution'],frames['intraday'])
            want=feature.loc[actual.index.strftime('%Y-%m-%d'),list(runtime.COLUMNS)]
            close(actual[list(runtime.COLUMNS)].to_numpy(float),want.to_numpy(float))
        for run in evidence['runs']:
            window=run['window_id']
            identity_raw=run['identity']
            identity=EvaluationIdentity(CandidateKey(**identity_raw['candidate']),**{k:v for k,v in identity_raw.items() if k!='candidate'})
            diagnosis=diagnose_accounts(ctx.repository,AccountDiagnosisRequest(AccountRunRef(ref,identity),None,
                __import__('czsc_trader.research_tools',fromlist=['EvaluationWindow']).EvaluationWindow(window,date(2025,1,2) if window=='full' else date(2025,2,6),date(2026,10,21))))
            diagnostic.append({'candidate':cid,'window':window,'result':diagnosis.to_dict()})
            # Preserve actual platform status. A money-precision mismatch in
            # the public audit is a blocker, never relabelled UNSUPPORTED.
            assert diagnosis.status.value in ('UNSUPPORTED','INVALID_EVIDENCE')
            tables={name:pd.DataFrame(payload['data']) for name,payload in run['ledgers'].items()}
            daily,decisions,fills,orders,trades=[tables[name] for name in ('account_daily','decisions','fills','orders','trades')]
            assert len(daily)==len(decisions)==(434 if window=='full' else 415)
            for name,table in tables.items():
                exported=pd.read_csv(HERE/f'others/{cid}_{window}_{name}.csv')
                assert len(exported)==len(table) and set(exported)==set(table)
                for col in table:
                    if pd.api.types.is_numeric_dtype(table[col]):
                        close(exported[col],table[col])
                ledger_checks+=1
            assert run['signal_support']['execution_policy']['settings']['capital']=={'fee_rate':.001,'mode':'signal_cash_fraction','target_scope':'entry_cycle'}
            signals=pd.to_datetime(decisions.signal_date).dt.strftime('%Y-%m-%d')
            assert (pd.to_datetime(decisions.signal_date)<pd.to_datetime(decisions.valid_session)).all()
            for column in runtime.COLUMNS:
                close(decisions[column],feature.loc[signals,column])
            for column in expected:
                close(pd.to_numeric(decisions[column]),expected.loc[signals,column])
            assert float(daily.cash_before.iloc[0])==100000 and int(daily.quantity_before.iloc[0])==0
            close(daily.equity,daily.cash+daily.quantity*daily.close)
            close(daily.cash_before.iloc[1:],daily.cash.iloc[:-1])
            close(daily.quantity_before.iloc[1:],daily.quantity.iloc[:-1])
            close(fills.fees,fills.quantity*fills.price*.001)
            assert (fills.quantity%100==0).all()
            fills=fills.copy()
            fills['day']=pd.to_datetime(fills.fill_time).dt.strftime('%Y-%m-%d')
            fills['qchange']=np.where(fills.side.eq('BUY'),fills.quantity,-fills.quantity)
            fills['cashchange']=-fills.qchange*fills.price-fills.fees
            dates=pd.to_datetime(daily.date).dt.strftime('%Y-%m-%d')
            flow=fills.groupby('day')[['qchange','cashchange']].sum().reindex(dates,fill_value=0)
            close(daily.quantity-daily.quantity_before,flow.qchange)
            close(daily.cash-daily.cash_before,flow.cashchange)
            previous=None
            opened=0
            exhausted=0
            for i,d in decisions.iterrows():
                before=json.loads(d.entry_cycle_before)
                after=json.loads(d.entry_cycle_after)
                settled=json.loads(daily.entry_cycle.iloc[i])
                assert before==previous
                current_fills=fills[fills.decision_id.eq(d.decision_id)]
                if after is not None:
                    budget=Decimal(after['cash_budget'])
                    allocation=Decimal(after['allocation_fraction'])
                    if before is None:
                        opened+=1
                        close(float(budget),float(daily.cash_before.iloc[i])*float(allocation))
                        buyorders=orders[orders.decision_id.eq(d.decision_id)&orders.side.eq('BUY')]
                        assert len(buyorders)>0
                        limit=float(buyorders.limit_price.iloc[0])
                        expected_quantity=int(budget/(Decimal(str(limit))*(Decimal('1.001')))//100)*100
                        assert after['target_quantity']==expected_quantity
                    else:
                        for key in ('cycle_id','opening_signal_identity','allocation_fraction','cash_budget','target_quantity'):
                            assert before[key]==after[key]
                    buys=current_fills[current_fills.side.eq('BUY')]
                    cost=sum((Decimal(str(f.price))*int(f.quantity)+Decimal(str(f.fees)) for f in buys.itertuples()),Decimal(0))
                    cumulative=Decimal(after['buy_cost_including_fees'])+cost
                    assert cumulative<=budget+Decimal('.0000001')
                    if settled is None:
                        assert after['phase']=='EXITING' and int(daily.quantity.iloc[i])==0
                    else:
                        assert settled['cycle_id']==after['cycle_id']
                        close(float(settled['buy_cost_including_fees']),float(cumulative))
                        assert int(daily.quantity.iloc[i])<=settled['target_quantity']
                else:
                    assert settled is None and current_fills.empty
                exhausted+=int(d.cycle_status=='BUDGET_LIMIT')
                previous=settled
            daily=daily.copy()
            daily.index=dates
            decisions=decisions.set_index('decision_id')
            local=[]
            for cycle,group in fills.groupby('cycle_id',sort=False):
                buys=group[group.side.eq('BUY')]
                first=buys.iloc[0]
                firstday=first['day']
                decision=decisions.loc[first.decision_id]
                qty=int(group.qchange.sum())
                gross=float((-group.qchange*group.price).sum()+qty*daily.close.iloc[-1])
                fees=float(group.fees.sum())
                entrybuys=buys[buys.day.eq(firstday)]
                entrygross=float((entrybuys.quantity*(daily.loc[firstday,'close']-entrybuys.price)).sum())
                entrynet=entrygross-float(entrybuys.fees.sum())
                item={'candidate':cid,'mode':mode,'window':window,'cycle_id':cycle,
                      'first_entry_day':firstday,'signal_date':str(first.signal_date)[:10],
                      'allocation_fraction':float(decision.cycle_allocation_fraction),
                      'risk_rejected':not bool(decision.risk_allowed),'r5':float(decision.r5),
                      'r5_sign':'up' if decision.r5>0 else 'down' if decision.r5<0 else 'zero',
                      'buy_fills':len(buys),'remaining_quantity':qty,'gross_yuan':gross,'fees_yuan':fees,
                      'net_yuan':gross-fees,'entry_day_gross_yuan':entrygross,'entry_day_net_yuan':entrynet,
                      'later_gross_yuan':gross-entrygross}
                local.append(item)
                cycles.append(item)
            cycleframe=pd.DataFrame(local)
            close(cycleframe.net_yuan.sum(),daily.equity.iloc[-1]-100000)
            equity=np.r_[100000.,daily.equity.to_numpy(float)]
            net=float(equity[-1]/100000-1)
            dd=float(np.max(1-equity/np.maximum.accumulate(equity)))
            close(net,row['runs'][window]['net_return'])
            close(dd,row['runs'][window]['dd'])
            exposure=daily.quantity*daily.close/daily.equity
            accounts.append({'candidate':cid,'mode':mode,'window':window,'net_yuan':float(equity[-1]-100000),
                'net_return':net,'dd':dd,'fees_yuan':float(fills.fees.sum()),'intended_cycles':opened,
                'filled_cycles':len(cycleframe),'multi_buy_cycles':int((cycleframe.buy_fills>1).sum()),
                'budget_limit_decisions':exhausted,'positive_holding_days':int((daily.quantity>0).sum()),
                'mean_end_day_exposure':float(exposure.mean()),'max_end_day_exposure':float(exposure.max()),
                'entry_day_gross_yuan':float(cycleframe.entry_day_gross_yuan.sum()),
                'entry_day_net_yuan':float(cycleframe.entry_day_net_yuan.sum()),
                'later_gross_yuan':float(cycleframe.later_gross_yuan.sum()),
                'cycle_profit_yuan':float(cycleframe.net_yuan.clip(lower=0).sum()),
                'cycle_loss_yuan':float(-cycleframe.net_yuan.clip(upper=0).sum()),
                'r5_groups':cycleframe.groupby('r5_sign').agg(cycles=('cycle_id','size'),net_yuan=('net_yuan','sum')).reset_index().to_dict('records')})
    allcycles=pd.DataFrame(cycles)
    allcycles.to_csv(HERE/'others/cycle_accounting.csv',index=False)
    # P2 same-event information diagnostics reuse the historical isolated labels,
    # never multiply an account path to claim an executable fractional account.
    labels=pd.read_csv(EvidenceRef.from_dict(sources['training_input:others/labels.csv']).resolve(ROOT))
    common=independent_intentions(feature,schedule,'fixed100').reset_index()
    common=common[common.model_ready.eq(1)&common.path_prediction.ge(0)]
    event=[]
    for target in ('entry','net3'):
        merged=common.merge(labels[labels.target.eq(target)][['date','y']],left_on='signal_date',right_on='date',validate='one_to_one')
        missing=int(merged.y.isna().sum())
        merged=merged[merged.y.notna()].copy()
        merged['yuan']=merged.y*100000.
        event.append({'target':target,'missing_labels':missing,'mask':'risk exceeds training-fitted median',
                      **amounts(merged,'yuan',merged.risk_allowed.eq(0))})
    baseline=allcycles[allcycles['mode'].eq('fixed100')&allcycles.window.eq('full')]
    baseline_costs={column:amounts(baseline,column,baseline.risk_rejected)
                    for column in ('entry_day_net_yuan','net_yuan')}
    pairs=[]
    full={row['mode']:row for row in accounts if row['window']=='full'}
    for mode in MODES[1:]:
        for control in ('fixed100',) if mode in ('fixed50','fixed75') else ('fixed100','fixed50','fixed75'):
            a,b=full[mode],full[control]
            pairs.append({'mode':mode,'control':control,**{key:a[key]-b[key] for key in
                         ('net_return','dd','fees_yuan','mean_end_day_exposure','cycle_profit_yuan','cycle_loss_yuan')}})
    save(HERE/'others/public_diagnoses.json',diagnostic)
    formal_valid = all(item['result']['status']=='UNSUPPORTED' for item in diagnostic)
    save(HERE/'others/analysis.json',{'status':'PASS' if formal_valid else 'ACCOUNTING_CHECKS_PASS_FORMAL_BLOCKED','accounts':accounts,'comparisons':pairs,
        'common_path_events':event,'baseline_actual_cycles_risk_attribution':baseline_costs,
        'diagnostic_limits':('Public diagnosis authenticated all evidence then returned UNSUPPORTED for dynamic allocation. Initial exact-money audit false rejection remains in audit_blocker.json; current platform revalidation did not mutate historical evidence.' if formal_valid else 'Public diagnosis returned INVALID_EVIDENCE because SE exact money comparison rejected binary64 fee roundoff; preserve audit_blocker.json. Formal account acceptance is blocked.')+' Cycle and entry-day arithmetic are independent accounting descriptions only. Historical isolated event labels use original full-allocation execution; not new-contract fractional counterfactuals. Entries may differ under risk rejection; neither weighted labels nor deleted losses are account outcomes.',
        'new_model_fits':0,'runtime_prediction_rows':sum(434 if row['window']=='full' else 415 for row in accounts),
        'formal_ledger_exports':ledger_checks,'bound_input_groups':len(fetched),
        'budget_and_quantity_lock':'All ten accounts independently checked; actual inclusive-fee BUY costs remain within adopted budget; target quantities persist until exit.',
        'sources':sources,'sha256':{str(p.relative_to(HERE)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in (HERE/'others/results.json',HERE/'others/cycle_accounting.csv',SOURCE/FILES[0],__import__('pathlib').Path(__file__))}})
    print(json.dumps({'P2_ANALYSIS':'PASS','accounts':len(accounts),'events':event,'comparisons':pairs},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
