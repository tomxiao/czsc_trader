"""Optimistic opportunity-count upper bounds; no account or return evaluation."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,time
from itertools import combinations
import importlib.util,json,sys
import pandas as pd
import requests
from trading_execution_engine import OrderSpec,DailyQuote,SessionPriceLimits,resolve_fill
ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def maximum(eligible,N,H,first_sell):
    """DAG recurrence considers every skip/enter choice, including delayed exits."""
    dp=[0]*(N+2);choice={}
    for e in range(N,0,-1):
        dp[e]=dp[e+1]
        if e in eligible and e in first_sell:
            next_entry=max(e+H+1,first_sell[e]+1)
            score=1+dp[min(next_entry,N+1)]
            if score>=dp[e]:dp[e]=score;choice[e]=next_entry
    witness=[];e=1
    while e<=N:
        if e in choice:witness.append(e);e=choice[e]
        else:e+=1
    assert len(witness)==dp[1]
    return dp[1],witness

def synthetic():
    checks=0
    N=7
    for mask in range(1<<N):
        opportunities={i+1 for i in range(N) if mask&(1<<i)}
        for H in (1,2,3,4):
            for delay in (1,H):
                # Some exits deliberately delayed: greedy earliest entry need not be optimal.
                sells={e:e+delay+(2 if e%3==1 else 0) for e in opportunities}
                sells={e:s for e,s in sells.items() if s<=N}
                got,_=maximum(opportunities,N,H,sells);expected=0
                for size in range(len(opportunities)+1):
                    for subset in combinations(sorted(opportunities),size):
                        if all(e in sells for e in subset) and all(b>=max(a+H+1,sells[a]+1) for a,b in zip(subset,subset[1:])):expected=max(expected,size)
                assert got==expected;checks+=1
    # Earliest entry e1 locks until6; skipping permits e2,e4 (H1).
    assert maximum({1,2,4},6,1,{1:5,2:3,4:5})==(2,[2,4])
    return checks+1

def main():
    dest=EX/'others/capacity_upper_bound.json'
    if dest.exists():raise RuntimeError('Preserve completed diagnostic')
    attempts=[]
    def block(*a,**kw):attempts.append(1);raise RuntimeError('No upstream')
    requests.sessions.Session.request=block
    checks=synthetic()
    auditpath=EX.parent/'EX017_20261017/src/audit_accounts.py';sys.path.insert(0,str(auditpath.parent))
    audit=module('ex017_capacity_inputs',auditpath);frames=audit.load_frames()
    runtimepath=EX/'src/strategy_runtime/strategies/repair.py';runtime=module('ex027_capacity_runtime',runtimepath)
    inputs={k:v.set_index(pd.to_datetime(v.Date)).sort_index() for k,v in frames.items()}
    market=inputs['stock.ohlcv'];raw=inputs['stock.unadjusted_daily'].reindex(market.index);limits=inputs['security.price_limits'];status=inputs['security.trading_status']
    dates=market.index;assert dates[0]==pd.Timestamp('2019-12-31');N=len(dates)-1;assert N==1642 and dates[1]==pd.Timestamp('2020-01-02')
    scale=market.Close/raw.Close
    support=market.Close.where(dates>=pd.Timestamp('2020-01-02')).shift(1).rolling(5).min()
    eligible=set();sellable=set();opportunities=[]
    for e in range(1,N+1):
        day=dates[e];r=market.iloc[e];trading=status.loc[day,'Status']=='TRADING'
        signal_ready=e-1>=60;support_ok=bool(market.Close.iloc[e-1]>=support.iloc[e-1]);buy_filled=False
        if trading:
            b=limits.loc[day];rules=SessionPriceLimits(day.date(),float(b.DownLimit*scale.iloc[e]),float(b.UpLimit*scale.iloc[e]),float(.01*scale.iloc[e]))
            kwargs=dict(session_open=float(r.Open),session_time=datetime.combine(day.date(),time(9,30)),intraday_touches=(),daily_quote=DailyQuote(float(r.Low),float(r.High)),session_limits=rules)
            sell=resolve_fill(OrderSpec('SELL','MARKET',100),**kwargs)
            if sell.filled:sellable.add(e)
            if signal_ready and support_ok:
                limit=runtime.buy_limit(float(raw.Close.iloc[e-1]),float(scale.iloc[e-1]))
                buy=resolve_fill(OrderSpec('BUY','LIMIT',100,limit),**kwargs);buy_filled=bool(buy.filled)
                if buy_filled:eligible.add(e)
        opportunities.append(dict(session=e,date=str(day.date()),prior_signal_ready=signal_ready,prior_support_ok=support_ok,buy_fillable=buy_filled,sell_fillable=e in sellable))
    rows=[]
    for H in (15,18):
        for mode,delay in (('fixed_exit',H),('reserved_optimistic_early_exit',1)):
            ideal={e:e+delay for e in eligible if e+delay<=N}
            executable={e:next((s for s in range(e+delay,N+1) if s in sellable),None) for e in eligible}
            executable={e:s for e,s in executable.items() if s is not None}
            count,witness=maximum(eligible,N,H,executable);relaxed,_=maximum(eligible,N,H,ideal)
            assert count<=relaxed
            assert all(e in eligible and executable[e]<=N for e in witness)
            assert all(b>=max(a+H+1,executable[a]+1) for a,b in zip(witness,witness[1:]))
            rows.append(dict(horizon=H,mode=mode,ideal_calendar_upper=((N-60)//(H+1) if delay==H else 1+(N-62)//(H+1)),eligible_buy_ideal_sell_upper=relaxed,eligible_buy_public_sell_upper=count,frequency_upper=60*count/N,required_closed=83,excluded_by_frequency=count<83,witness=[dict(entry_session=e,entry_date=str(dates[e].date()),optimistic_exit_session=executable[e],optimistic_exit_date=str(dates[executable[e]].date())) for e in witness]))
    paths=[Path(__file__),runtimepath,auditpath,EX.parent/'EX017_20261017/src/pinned_inputs.py',EX.parent/'EX025_20261018/others/frequency_feasibility.json']
    result=dict(status='PASS',new_accounts=0,new_trials=0,upstream_calls=0,synthetic_exhaustive_checks=checks,evaluation_sessions=N,first_possible_entry_session=61,eligible_buy_dates=len(eligible),prepared_reference=audit.FULL_INPUT_REFERENCE,source_sha256={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},input_canonical_csv_sha256={k:sha256(v.to_csv(index=False,lineterminator='\n').encode()).hexdigest() for k,v in frames.items()},proof={'superset':'Every actual entry must be in the prior-ready/support, public-limit-fillable set. Cash/lot affordability is ignored; every opportunity may be skipped; failed-buy reset is ignored. Early exits may occur at the first public SELL-fillable session after E+1 irrespective of support/P conditions. Every real legal path is therefore in or dominated by this relaxed timing set.','recurrence':'D[e]=max(D[e+1],1+D[max(E+H+1,first_possible_public_sell(E)+1)]), eligible entries only; beyondN=0. Maximizes count over all possible choices, not a single greedy schedule.','exit_dominance':'For a fixed entry, any actual SELL is no earlier than the chosen public-fillable earliest exit. Replacing a real exit with that optimistic exit cannot delay any later entry. Thus using earliest legal SELL preserves an upper bound even if actual branch decisions differ.','indices':'Evaluation session1=2020-01-02; sourceindex0=2019-12-31 is excluded from warmup/support.','no_profit_use':'DP optimizes only opportunity count; witness is an optimistic retrospective feasibility certificate, not an executable strategy or a tested return.'},rows=rows,limits=['An upper below83 rules out the uniform H mechanism under current contracts. An upper at least83 proves neither actual count nor profitability.','Early-exit upper applies both R/P as a relaxation; it does not assert either rule actually exits that early.','H15/H18 are requested feasibility checks, not newly registered configurations.'])
    assert not attempts
    table=EX/'others/capacity_opportunities.csv';table.write_text(pd.DataFrame(opportunities).to_csv(index=False,lineterminator='\n'),encoding='utf-8',newline='\n')
    result['opportunity_table_sha256']=sha256(table.read_bytes()).hexdigest()
    dest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:result[k] for k in ('status','synthetic_exhaustive_checks','eligible_buy_dates')}));print(json.dumps([{k:v for k,v in r.items() if k!='witness'} for r in rows]))
if __name__=='__main__':main()
