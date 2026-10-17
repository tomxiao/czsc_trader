"""Offline EX020 outcome and entry-path diagnostics; never runs an account."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
PRIOR=ROOT/'research/S014/experiments/EX018_20261017/src/account_diagnostics.py'
spec=importlib.util.spec_from_file_location('s014_cycle_core',PRIOR)
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
BEST='renewal_parent_H3_cap0'


def main():
    out=EX/'others/path_diagnostics.json'
    if out.exists():
        raise RuntimeError('Preserve completed evidence')
    requests.sessions.Session.request=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Offline only'))
    source=EX/'others/comparison_accounts.json'
    if not source.exists():
        raise RuntimeError('Wait for completed formal comparison manifest')
    records=json.loads(source.read_text(encoding='utf-8'))['records']
    selected={r['variant']:r for r in records}
    assert len(selected)==10 and all(r['status']=='SUCCEEDED' for r in records)
    tables={v:core.load(r) for v,r in selected.items()}
    comparison=json.loads((EX/'others/comparison.json').read_text(encoding='utf-8'))
    annual=pd.read_csv(EX/'others/annual_comparison.csv')
    summaries=pd.read_csv(EX/'others/account_comparison.csv')
    candidates=[v for v in selected if v.startswith('renewal_')]
    all_cycles,recon,pairs,decomp,missed,exposure=[],[],[],[],[],[]
    for window,cutoff in [('ALL',pd.Timestamp('2026-10-15')),('WITHOUT2026',pd.Timestamp('2025-12-31'))]:
        current={}
        for variant,t in tables.items():
            c,check=core.cycles(t,cutoff,variant)
            c['window']=window
            current[variant]=c
            all_cycles.append(c);recon.append(check)
            daily=t['account_daily'].loc[:cutoff]
            index=daily.index
            lengths=[int(index.get_loc(pd.Timestamp(r.exit_or_mark_date))-index.get_loc(pd.Timestamp(r.entry_date))) for r in c.itertuples()]
            exposure.append(dict(window=window,variant=variant,entries=len(c),closed=int(c.status.eq('CLOSED').sum()),
                                 exposure_close_sessions=int(daily.quantity.gt(0).sum()),
                                 mean_elapsed_sessions=float(np.mean(lengths)),max_elapsed_sessions=int(max(lengths)),
                                 holds_over12=int(np.sum(np.array(lengths)>12)),actual_return=check['actual_return']))
        for baseline in ['baseline_H3','baseline_H6']:
            for candidate in candidates:
                joined,unused=core.compare(current[baseline],current[candidate],f'{candidate}_minus_{baseline}',window)
                joined['baseline']=baseline;joined['candidate']=candidate
                pairs.append(joined)
                for cohort,part in core.scopes(joined):
                    row=dict(window=window,baseline=baseline,candidate=candidate,entry_cohort=cohort)
                    for cat in ['matched','left_only','right_only']:
                        q=part.loc[part.category.eq(cat)]
                        row[cat+'_n']=len(q)
                        row[cat+'_cycle_log']=float(q.cycle_log_difference.sum())
                    row['total_cycle_log_difference']=float(part.cycle_log_difference.sum())
                    if cohort=='ALL':
                        expected=float(current[candidate].cycle_log.sum()-current[baseline].cycle_log.sum())
                        assert abs(expected-row['total_cycle_log_difference'])<1e-10
                    decomp.append(row)
                if candidate==BEST and baseline=='baseline_H3':
                    right=tables[candidate]
                    sells=pd.to_datetime(right['fills'].loc[right['fills'].side.eq('SELL'),'fill_time']).dt.normalize()
                    for r in joined.loc[joined.category.eq('left_only')].itertuples():
                        day=pd.Timestamp(r.entry_date)
                        d=right['account_daily'].loc[day]
                        active=current[candidate].loc[current[candidate].entry_date.lt(r.entry_date)&current[candidate].exit_or_mark_date.ge(r.entry_date)]
                        assert len(active)==1 and d.quantity_before>0
                        a=active.iloc[0]
                        missed.append(dict(window=window,entry_date=r.entry_date,year=day.year,
                                           baseline_exit=r.exit_or_mark_date_left,baseline_net_return=float(r.position_return_left),
                                           missing_cycle_log=float(r.cycle_log_difference),candidate_exits_same_session=bool(day in sells.to_list()),
                                           candidate_active_entry=a.entry_date,candidate_active_exit=a.exit_or_mark_date,
                                           candidate_active_net_return=float(a.position_return)))
    contrasts=[]
    indexed=annual.set_index(['variant','year'])
    for v in candidates:
        for base in ['baseline_H3','baseline_H6']:
            for y in range(2020,2027):
                a,b=indexed.loc[(v,y)],indexed.loc[(base,y)]
                contrasts.append(dict(candidate=v,baseline=base,year=y,return_delta=float(a['return']-b['return']),
                                      drawdown_delta=float(a.max_drawdown-b.max_drawdown),return_=float(a['return']),
                                      required_return=float(a.required_return),drawdown=float(a.max_drawdown),
                                      return_pass=bool(a.return_pass),drawdown_pass=bool(a.drawdown_pass)))
    factorial=[]
    for h in [3,6]:
        for cap in [0,12]:
            left=f'renewal_qualified_H{h}_cap{cap}';right=f'renewal_parent_H{h}_cap{cap}'
            factorial.append((f'parent_minus_qualified_H{h}_cap{cap}',left,right))
        for renewal in ['qualified','parent']:
            left=f'renewal_{renewal}_H{h}_cap12';right=f'renewal_{renewal}_H{h}_cap0'
            factorial.append((f'uncapped_minus_cap12_{renewal}_H{h}',left,right))
    factorial_rows=[]
    for name,left,right in factorial:
        for y in range(2020,2027):
            a,b=indexed.loc[(right,y)],indexed.loc[(left,y)]
            factorial_rows.append(dict(comparison=name,year=y,return_delta=float(a['return']-b['return']),
                                       drawdown_delta=float(a.max_drawdown-b.max_drawdown)))
    missed_df=pd.DataFrame(missed)
    missed_summary=[]
    for window in ['ALL','WITHOUT2026']:
        m=missed_df.loc[missed_df.window.eq(window)]
        for scope,q in [('ALL',m),*[(str(y),m.loc[m.year.eq(y)]) for y in range(2020,2027)]]:
            for kind,r in [('ALL',q),('EXIT_SESSION',q.loc[q.candidate_exits_same_session]),('STILL_HELD',q.loc[~q.candidate_exits_same_session])]:
                missed_summary.append(dict(window=window,entry_cohort=scope,kind=kind,n=len(r),
                                           underlying_trade_returns=core.distribution(r.baseline_net_return),
                                           missing_cycle_log=float(r.missing_cycle_log.sum())))
    output_frames={'cycles':pd.concat(all_cycles,ignore_index=True),'matches':pd.concat(pairs,ignore_index=True),
                   'decomposition':pd.DataFrame(decomp),'exposure':pd.DataFrame(exposure),
                   'annual_contrasts':pd.DataFrame(contrasts),'factorial_contrasts':pd.DataFrame(factorial_rows),
                   'best_missed_entries':missed_df,'best_missed_summary':pd.json_normalize(missed_summary),
                   'reconciliation':pd.DataFrame(recon)}
    hashes={}
    for name,f in output_frames.items():
        p=EX/f'others/path_diagnostics_{name}.csv'
        if p.exists():
            raise RuntimeError('Preserve '+p.name)
        f.to_csv(p,index=False,lineterminator='\n')
        hashes[p.name]=sha256(p.read_bytes()).hexdigest()
    result=dict(status='PASS',account_runs=0,source_calls=0,sources=selected,
                script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),core_sha256=sha256(PRIOR.read_bytes()).hexdigest(),
                comparison_manifest_sha256=sha256(source.read_bytes()).hexdigest(),
                checks=dict(reconciliations=len(recon),max_absolute_return_error=max(r['absolute_reconciliation_error'] for r in recon),
                            all_formal_source_hashes_verified=True,all_matched_entry_prices_identical=True),
                method=['Same actual entry dates; matched/left-only/right-only cycle log terms sum to actual account log difference.',
                        'Include residual cash and genuine marked open positions without hypothetical exit fee.',
                        'WITHOUT2026 truncates account at 2025-12-31. Yearly path summaries use entry cohorts; annual_contrasts use actual NAV years.',
                        'A missed baseline entry on the candidate liquidation session is a historical opportunity conflict, not an achievable delayed re-entry return.',
                        'No new account, no future winners selected as new signals; positive/negative missed trades both retained.',
                        'Exposure duration is trading-session index distance from actual entry to exit/mark; open duration is right-censored.'],
                reconciliation=recon,exposure=exposure,decomposition=decomp,annual_contrasts=contrasts,
                factorial_contrasts=factorial_rows,best_missed_summary=missed_summary,
                target_pass_count=comparison['all_targets_pass_count'],outputs=hashes)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','checks':result['checks'],
                      'best_decomposition':[r for r in decomp if r['candidate']==BEST and r['entry_cohort']=='ALL'],
                      'missed':[r for r in missed_summary if r['entry_cohort']=='ALL']},indent=2))


if __name__=='__main__':
    main()
