"""Known-at-close early-exit states; labels use existing authenticated accounts."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import sys
import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def main():
    out=EX/'others/loss_state_diagnostics.json'
    if out.exists():raise RuntimeError('Preserve existing diagnosis')
    requests.sessions.Session.request=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('No upstream access'))
    core=module('loss_cycle_core',EX.parent/'EX018_20261017/src/account_diagnostics.py')
    audit_source=EX.parent/'EX017_20261017/src'
    sys.path.insert(0,str(audit_source))
    audit=module('loss_pinned_frames',audit_source/'audit_accounts.py')
    prices=audit.load_frames();args=[prices[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    strategy=module('loss_reserve_strategy',EX/'src/strategy_runtime/strategies/repair.py')
    history=strategy.history(*args,'support_exit_reserve_H10')
    market=args[0].set_index(pd.to_datetime(args[0].Date)).sort_index()
    records=json.loads((EX/'others/comparison_accounts.json').read_text(encoding='utf-8'))['records']
    records=[r for r in records if r['variant'] in ('support_entry_H10','support_exit_reserve_H10')]
    tables={r['variant']:core.load(r) for r in records}
    daily=tables['support_exit_reserve_H10']['account_daily']
    anchor=float(market.loc[daily.index[0],'Close']/daily.close.iloc[0])
    rows=[];reconciliations=[]
    for window,cutoff in [('ALL',pd.Timestamp('2026-10-15')),('WITHOUT2026',pd.Timestamp('2025-12-31'))]:
        bc,br=core.cycles(tables['support_entry_H10'],cutoff,'support_entry_H10')
        rc,rr=core.cycles(tables['support_exit_reserve_H10'],cutoff,'support_exit_reserve_H10')
        reconciliations.extend([br,rr]);bmap={r['entry_date']:r for r in bc.to_dict('records')}
        previous_broken_floor=None
        for r in rc.to_dict('records'):
            e=pd.Timestamp(r['entry_date']);i=history.index.get_loc(e);signal=i-1
            assert history.iloc[i].buy_filled_today
            entry_close=float(market.Close.iloc[signal]);entry_open=float(market.Open.iloc[signal])
            entry_parent=bool(entry_open<market.Close.iloc[signal-1] and entry_close>entry_open)
            entry_below_previous_break=None if previous_broken_floor is None else bool(entry_close<previous_broken_floor)
            pending=history.iloc[i:].loc[lambda f:(f.index<=min(pd.Timestamp(r['exit_or_mark_date']),cutoff)) & f.exit_pending]
            trigger=None if pending.empty else pending.index[0]
            if trigger is None:
                trigger_index=None;early=False;profit=None;parent=None;falling=None
            else:
                trigger_index=history.index.get_loc(trigger);early=trigger_index<i+9
                price=float(market.loc[trigger,'Close']/anchor)
                profit=float(price/(r['entry_price']*1.001)-1)
                parent=bool(market.Open.iloc[trigger_index]<market.Close.iloc[trigger_index-1] and market.Close.iloc[trigger_index]>market.Open.iloc[trigger_index])
                falling=bool(history.support_floor.iloc[trigger_index]<history.support_floor.iloc[trigger_index-1])
            b=bmap.get(r['entry_date']);paired=bool(b and b['status']=='CLOSED' and r['status']=='CLOSED')
            rows.append(dict(window=window,entry_date=r['entry_date'],entry_year=r['entry_year'],exit_or_mark_date=r['exit_or_mark_date'],status=r['status'],
                decision_date=None if trigger is None else str(trigger.date()),decision_year=None if trigger is None else trigger.year,early_break=early,
                close_net_of_buy_fee_return=profit,positive_mark=None if profit is None else profit>0,
                decision_parent=parent,decision_support_floor_falling=falling,entry_parent=entry_parent,
                entry_up_candle=bool(entry_close>entry_open),entry_below_previous_broken_floor=entry_below_previous_break,
                matched_B_entry=b is not None,both_closed=paired,R_position_return=r['position_return'],R_cycle_log=r['cycle_log'],
                B_position_return=None if b is None else b['position_return'],
                early_exit_increment=None if not paired else r['position_return']-b['position_return'],
                actual_cycle_log_increment=None if not paired else r['cycle_log']-b['cycle_log']))
            previous_broken_floor=float(history.loc[trigger,'support_floor']) if early else None
    frame=pd.DataFrame(rows);summaries=[]
    dimensions=('positive_mark','decision_parent','decision_support_floor_falling')
    for window,df in frame.groupby('window',sort=False):
        for year in ('ALL',*range(2020,2027)):
            d=df if year=='ALL' else df[df.entry_year==year]
            for dim in dimensions:
                for state in (False,True):
                    g=d[d.early_break & d.both_closed & d[dim].eq(state)]
                    v=g.early_exit_increment.astype(float)
                    summaries.append(dict(window=window,entry_cohort=year,dimension=dim,state=state,n=len(g),
                        mean_increment=None if g.empty else float(v.mean()),median_increment=None if g.empty else float(v.median()),
                        positive_n=int((v>1e-12).sum()),negative_n=int((v< -1e-12).sum()),
                        positive_increment_sum=float(v[v>0].sum()),negative_increment_sum=float(v[v<0].sum()),net_increment_sum=float(v.sum()),
                        worst_increment=None if g.empty else float(v.min()),
                        mean_remove_top3=None if len(g)<=3 else float(v.sort_values().iloc[:-3].mean()),
                        mean_remove_top5=None if len(g)<=5 else float(v.sort_values().iloc[:-5].mean()),
                        cycle_log_increment=float(g.actual_cycle_log_increment.sum())))
    entry_summaries=[]
    for window,df in frame.groupby('window',sort=False):
        for year in ('ALL',*range(2020,2027)):
            d=df if year=='ALL' else df[df.entry_year==year]
            for dim in ('entry_below_previous_broken_floor','entry_parent','entry_up_candle'):
                for state in (False,True):
                    g=d[d[dim].eq(state)];v=g.R_cycle_log
                    entry_summaries.append(dict(window=window,entry_cohort=year,dimension=dim,state=state,n=len(g),
                        positive_n=int((v>0).sum()),negative_n=int((v<0).sum()),positive_log=float(v[v>0].sum()),negative_log=float(v[v<0].sum()),net_log=float(v.sum()),
                        mean_position_return=None if g.empty else float(g.R_position_return.mean())))
    sources=[Path(__file__),EX/'src/strategy_runtime/strategies/repair.py',EX/'others/comparison_accounts.json',EX/'others/path_diagnostics.json']
    result=dict(status='PASS',new_accounts=0,new_upstream_calls=0,source_records=records,
        source_fingerprints=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(p.read_bytes()).hexdigest()) for p in sources],
        prepared_reference=audit.FULL_INPUT_REFERENCE,reconciliations=reconciliations,scale_anchor=anchor,
        early_exit_state_summaries=summaries,entry_state_summaries=entry_summaries,episodes=rows,
        methodology={'early':'First latched SELL decision strictly before actual entry source index+9; only actual B/R equal-entry and both-CLOSED pairs have fixed-H10 incremental labels.',
            'P':'Known at first support-break decision close: normalized HFQ close/(actual buy fill price*1.001)-1>0. Buy fee included; no future sell fee deducted. Zero threshold fixed, not searched.',
            'parent':'Known decision day Open<prior Close and Close>Open; original low-open recovery form, no additional threshold.',
            'floor_falling':'Current previous5 minimum less than previous-day previous5 minimum; known at close.',
            'entry_below_previous_broken_floor':'Current entry signal close below support floor stored at immediately previous actual cycle early-break decision. Null if previous cycle had no early break. Diagnostic actual-path label, not a simulated new entry policy.',
            'returns':'R-B position-return difference for same entry excludes capital path differences; actual residual-cash cyclelog difference shown separately. Entry-year cohorts are not calendar-year NAV.',
            'cutoff':'WITHOUT2026 uses actual 2025-12-31 mark; early-exit mean excludes either-leg OPEN/right-censored/unmatched cases. Such episodes retained separately.'},
        limits=['Existing account path diagnostic only; selecting a subset cannot reproduce a conditional exit account.','All outcomes are seen research labels, whereas split conditions are known at decision close.','Only fixed previously motivated price states evaluated; no threshold search and no new acceptance gate.'])
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('LOSS_STATE_DIAGNOSTICS_PASS',len(frame))


if __name__=='__main__':main()
