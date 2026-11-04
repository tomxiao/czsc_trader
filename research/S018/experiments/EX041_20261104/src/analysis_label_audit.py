"""Single-process read-only audit of EX041 price labels vs EX039/EX040."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal, ROUND_FLOOR
import importlib.util
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / 'research/S018'
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def materialize(ref):
    p = FAMILY/'assets/evidence'/ref['experiment']['experiment_id']/ref['evidence_id']
    raw = p.read_bytes()
    assert sha256(raw).hexdigest() == ref['sha256']
    return materialize_equity(raw, lambda x: (p.parent/(x['sha256']+'.json')).read_bytes()).payload
def main():
    src = FAMILY/'experiments/EX041_20261104/src/strategy.py'
    source_hash = sha256(src.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location('ex41_audited_strategy', src)
    strategy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(strategy)
    base = read(FAMILY/'experiments/EX025_20261104/others/results.json')['accounts']['C6300']['account_ref']
    view = materialize(base)
    bars = pd.DataFrame(view['audit_inputs']['bars'])
    dates = pd.to_datetime(bars.Date).dt.strftime('%Y-%m-%d').to_numpy()
    date_index = {d:i for i,d in enumerate(dates)}
    features, price_y, valid, fill = strategy.data(bars)
    event_path = FAMILY/'experiments/EX039_20261104/others/analysis_events_enriched.json'
    events = [e for e in read(event_path) if e['horizon']==1 and e['status']=='CLOSED']
    events = sorted(events, key=lambda e:e['signal_date'])
    assert len(events)==835
    extra_dates=sorted(set(dates[valid])-{e['signal_date'] for e in events})
    missing_dates=sorted({e['signal_date'] for e in events}-set(dates[valid]))
    assert extra_dates==['2024-05-02'] and not missing_dates
    formal_valid=valid & np.isin(dates,[e['signal_date'] for e in events])
    assert len(set(e['signal_date'] for e in events))==835
    formal_y = np.full(len(bars), np.nan)
    dividend_events = []
    cash_actions = [a for a in view['audit_inputs']['action_facts'] if a['Kind']=='CASH_DIVIDEND']
    other_actions = [a for a in view['audit_inputs']['action_facts'] if a['Kind']!='CASH_DIVIDEND']
    assert not other_actions
    residuals=[]
    for e in events:
        i=date_index[e['signal_date']]
        assert dates[i+1]==e['entry_date'] and dates[i+2]==e['exit_date']
        assert abs(fill[i]-e['entry_price']) < 1e-10
        assert abs(float(bars.Open.iloc[i+2])-e['exit_price']) < 1e-10
        formal_y[i]=e['net_return']
        dividend=sum(a['CashPerShare'] for a in cash_actions if e['entry_date']<a['Date'][:10]<=e['exit_date'])
        delta=formal_y[i]-price_y[i]
        residuals.append(abs(delta-dividend/(fill[i]*1.001)))
        if dividend:
            dividend_events.append({'signal_date':e['signal_date'],'entry_date':e['entry_date'],'exit_date':e['exit_date'],
                'cash_per_share':dividend,'price_return':float(price_y[i]),'formal_return':float(formal_y[i]),'label_delta':float(delta)})
    assert max(residuals)<5.1e-11
    accounts=read(FAMILY/'experiments/EX039_20261104/others/results.json')['accounts']
    open_events=[]; limits_checked=0; total_buys=0; expired=0
    for key,account in accounts.items():
        if str(account['config'][1])!='1': continue
        run=materialize(account['account_ref'])['runs']['candidate']
        closed_ids={t['cycle_id'] for t in run['trades'] if t['status']=='CLOSED'}
        orders={o['order_id']:o for o in run['orders']}
        expired+=sum(o['side']=='BUY' and o['status']=='EXPIRED' for o in run['orders'])
        for f in run['fills']:
            if f['side']!='BUY':continue
            total_buys+=1
            i=date_index[f['interval_start'][:10]]-1
            limit=float((Decimal(str(float(bars.Close.iloc[i])))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01'))
            assert abs(orders[f['order_id']]['limit_price']-limit)<1e-10
            assert abs(f['price']-fill[i])<1e-10
            if f['cycle_id'] in closed_ids: limits_checked+=1
            else:open_events.append({'candidate':key,'signal_date':dates[i],'entry_date':dates[i+1],'price':f['price'],'label_mature':bool(valid[i])})
    assert limits_checked==835 and total_buys==836 and expired==125 and len(open_events)==1
    assert not open_events[0]['label_mature']
    forecast_path=FAMILY/'experiments/EX040_20261104/others/analysis_forecasts.json'
    forecasts=[f for f in read(forecast_path) if f['horizon']==1 and f['model'] in ('mean','shock','decomposition')]
    models={'mean':[], 'shock':['drift','range_state','shock_today','shock_yesterday'],
        'decomposition':['drift','range_state','intraday','gap','shock_yesterday']}
    summary={m:{'forecast_count':0,'sign_change_count':0,'two_down_sign_change_count':0,'sign_changes':[],
        'dividend_only_changes':[],'extra_touch_label_only_changes':[],
        'max_prediction_delta':0.,'max_ex040_reproduction_error':0.} for m in models}
    prefix_checks=0
    for date in sorted({f['signal_date'] for f in forecasts}):
        i=date_index[date]
        px,py,pv,pfill=strategy.data(bars.iloc[:i+1])
        mask=valid & (np.arange(len(bars))+2<=i)
        assert np.array_equal(np.flatnonzero(pv),np.flatnonzero(mask))
        assert np.allclose(py[pv],price_y[mask],atol=0,rtol=0)
        assert np.allclose(px.iloc[-1],features.iloc[i],atol=0,rtol=0)
        prefix_checks+=1
    for old in forecasts:
        model=old['model']; i=date_index[old['signal_date']]
        mask=formal_valid & (np.arange(len(bars))+2<=i)
        proxy_mask=valid & (np.arange(len(bars))+2<=i)
        assert int(mask.sum())==old['train_n']
        assert dates[np.flatnonzero(mask)[-1]+2]==old['latest_label_exit']
        def predict(y,selected=mask):
            cols=models[model]
            if not cols:return float(y[selected].mean())
            fitted=make_pipeline(StandardScaler(),Ridge(alpha=10.))
            fitted.fit(features.loc[selected,cols].to_numpy(),y[selected])
            return float(fitted.predict(features.loc[[i],cols].to_numpy())[0])
        strict_price_pred=predict(price_y);price_pred=predict(price_y,proxy_mask); formal_pred=predict(formal_y)
        error=abs(formal_pred-old['prediction'])
        assert error<5.1e-11
        # Reproduce public strategy forecast on sampled physical prefixes.
        if i%37==0:
            direct,n=strategy.forecast(bars.iloc[:i+1],model)
            assert n==int(proxy_mask.sum()) and abs(direct-price_pred)<1e-12
        s=summary[model];s['forecast_count']+=1
        s['max_prediction_delta']=max(s['max_prediction_delta'],abs(formal_pred-price_pred))
        s['max_ex040_reproduction_error']=max(s['max_ex040_reproduction_error'],error)
        two_down=bool(bars.Close.iloc[i]<bars.Close.iloc[i-1]<bars.Close.iloc[i-2])
        details={'signal_date':old['signal_date'],'next_execution_date':dates[i+1],
            'formal_prediction':formal_pred,'strict_price_prediction':strict_price_pred,
            'price_prediction':price_pred,'two_down':two_down}
        if (strict_price_pred>0)!=(formal_pred>0):s['dividend_only_changes'].append(details)
        if (strict_price_pred>0)!=(price_pred>0):s['extra_touch_label_only_changes'].append(details)
        if (price_pred>0)!=(formal_pred>0):
            s['sign_change_count']+=1;s['two_down_sign_change_count']+=int(two_down)
            s['sign_changes'].append({'signal_date':old['signal_date'],'next_execution_date':dates[i+1],
                'formal_prediction':formal_pred,'price_prediction':price_pred,'two_down':two_down,
                'direction':'positive_to_nonpositive' if formal_pred>0 else 'nonpositive_to_positive'})
    # Read only finished EX041 ledgers: report local decision sensitivity on the
    # realized position path, never claim a recomputed counterfactual account.
    account_impacts={}
    result41=FAMILY/'experiments/EX041_20261104/others/results.json'
    if result41.exists():
        for candidate,account in read(result41)['accounts'].items():
            model,entry,exit_rule=account['config']
            if model=='none':continue
            run=materialize(account['account_ref'])['runs']['candidate']
            decisions={d['observed_through'][:10]:d for d in run['decisions']}
            impact={}
            for effect,key in [('combined','sign_changes'),('extra_touch_label','extra_touch_label_only_changes')]:
                rows=[]
                for change in summary[model][key]:
                    if entry=='two_down' and not change['two_down']:continue
                    decision=decisions[change['signal_date']]
                    reason=decision['explanation']['judgment']
                    if reason not in ('forecast entry','no opportunity'):continue
                    facts={f['key']:f['text'] for f in decision['explanation']['basis']}
                    assert abs(float(facts['forecast'])-change['price_prediction'])<1e-12
                    orders=[o for o in run['orders'] if o['decision_id']==decision['decision_id']]
                    rows.append({'signal_date':change['signal_date'],'execution_date':decision['execution_start'][:10],
                        'actual_reason':reason,'actual_target':decision['target'],
                        'actual_orders':[{'side':o['side'],'status':o['status'],'reason':o['reason']} for o in orders]})
                impact[effect]={'flat_eligibility_changes':len(rows),'dates':rows}
            account_impacts[candidate]={'config':account['config'],'effects':impact}
    result={'source_sha256':source_hash,'base_evidence_sha256':base['sha256'],
        'ex039_events_sha256':sha256(event_path.read_bytes()).hexdigest(),
        'ex040_forecasts_sha256':sha256(forecast_path.read_bytes()).hexdigest(),
        'checks':{'mature_label_signal_set_equal':False,'mature_proxy_labels':int(valid.sum()),'formal_mature_labels':835,
            'extra_proxy_signal_dates':extra_dates,'missing_proxy_signal_dates':missing_dates,'entry_and_exit_prices_equal_on_common_events':True,
            'closed_buy_limits_equal':limits_checked,'all_buy_limits_equal':total_buys,'expired':expired,
            'open_events':open_events,'physical_prefix_dates_checked':prefix_checks,
            'mature_training_sets_and_counts_equal':False,'max_label_residual_after_cash_dividend':max(residuals)},
        'dividend_label_events':dividend_events,'forecast_sign_comparison':summary,
        'ex041_realized_path_local_decision_sensitivity':account_impacts,
        'execution_note':'Actual PortfolioHistoricalExecutor calls resolve_fill without daily_quote (portfolio.py:561-564); uses open<=limit and intraday low<limit when inclusive_touch=False. The separate daily_quote branch uses <= but is NOT the active path for these accounts. EX039 C7001 2024-05-03 limit113.45=low113.45 was EXPIRED/LIMIT_NOT_CROSSED; proxy incorrectly includes its positive return label.',
        'causality_note':'At close t, most recent mature signal t-2 exits at open t. Last two labels in a physical prefix are NaN, excluded. New decision executes t+1.',
        'scope_note':'Prediction sign differences are entry eligibility differences when flat, not verified actual portfolio order changes. Two_down is evaluated on the same visible close history. EX040 stored returns are rounded to 10 decimals; rounding residual is separated from dividend effect.'}
    assert sha256(src.read_bytes()).hexdigest()==source_hash
    output=FAMILY/'experiments/EX041_20261104/others/analysis_label_audit.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'checks':result['checks'],'dividend_events':len(dividend_events),
        'summary':{m:{k:(len(v) if isinstance(v,list) else v) for k,v in s.items()} for m,s in summary.items()},
        'output':str(output)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
