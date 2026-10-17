"""Authenticated six-account path attribution; no account execution or source calls."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
PRIOR = ROOT / 'research/S014/experiments/EX018_20261017/src/account_diagnostics.py'
spec = importlib.util.spec_from_file_location('s014_ex018_cycle_diagnostics', PRIOR)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
BASELINES = ('baseline_H3', 'baseline_H6')
CANDIDATES = ('extend_profit', 'extend_rising', 'extend_both', 'extend_either')


def context(tables, entry):
    day = pd.Timestamp(entry)
    a = tables['account_daily'].loc[day]
    decisions = tables['decisions']
    d = decisions.loc[pd.to_datetime(decisions.valid_session).dt.normalize().eq(day)]
    assert len(d)==1
    r = d.iloc[0]
    return dict(quantity_before=int(a.quantity_before), quantity_after=int(a.quantity),
                action=str(r.action), target_position=float(a.target_position),
                entry_signal=bool(r.entry_signal), failed_buy_reset=bool(r.failed_buy_reset))


def main():
    out = EX / 'others/path_diagnostics.json'
    if out.exists():
        raise RuntimeError('Preserve completed evidence')
    requests.sessions.Session.request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Offline only'))
    manifest = EX / 'others/comparison_accounts.json'
    records = json.loads(manifest.read_text(encoding='utf-8'))['records']
    selected = {r['variant']: r for r in records}
    assert set(selected)==set(BASELINES+CANDIDATES)
    assert all(r['status']=='SUCCEEDED' for r in records)
    tables = {v: core.load(selected[v]) for v in BASELINES+CANDIDATES}
    all_cycles, recon, pairs, summaries, decompositions, episodes, annual = [], [], [], [], [], [], []
    for window, cutoff in [('ALL',pd.Timestamp('2026-10-15')),('WITHOUT2026',pd.Timestamp('2025-12-31'))]:
        current = {}
        checks = {}
        for variant, table in tables.items():
            c, check = core.cycles(table,cutoff,variant)
            c['window']=window
            all_cycles.append(c)
            recon.append(check)
            current[variant]=c
            checks[variant]=check
        for baseline in BASELINES:
            for candidate in CANDIDATES:
                name=f'{candidate}_minus_{baseline}'
                joined, summary = core.compare(current[baseline],current[candidate],name,window)
                joined['baseline']=baseline
                joined['candidate']=candidate
                for side, variant in [('left',baseline),('right',candidate)]:
                    contextual = [context(tables[variant],day) for day in joined.entry_date]
                    for field in contextual[0]:
                        joined[f'{side}_entry_day_{field}']=[r[field] for r in contextual]
                pairs.append(joined)
                summaries.extend(summary)
                for cohort, part in core.scopes(joined):
                    contributions = {cat:float(part.loc[part.category.eq(cat),'cycle_log_difference'].sum())
                                     for cat in ('matched','left_only','right_only')}
                    item=dict(window=window,baseline=baseline,candidate=candidate,entry_cohort=cohort,
                              counts={cat:int(part.category.eq(cat).sum()) for cat in contributions},
                              cycle_log_contributions=contributions,total_cycle_log_difference=float(part.cycle_log_difference.sum()),
                              position_log_difference=float(part.position_log_difference.sum()),
                              missing_baseline_entries_candidate_holding=int((part.category.eq('left_only')&part.right_entry_day_quantity_before.gt(0)).sum()),
                              new_entries_baseline_holding=int((part.category.eq('right_only')&part.left_entry_day_quantity_before.gt(0)).sum()))
                    if cohort=='ALL':
                        actual_log=checks[candidate]['actual_log']-checks[baseline]['actual_log']
                        error=abs(item['total_cycle_log_difference']-actual_log)
                        assert error<1e-10
                        item.update(actual_nav_log_difference=actual_log,absolute_decomposition_error=error,
                                    baseline_actual_return=checks[baseline]['actual_return'],candidate_actual_return=checks[candidate]['actual_return'])
                    decompositions.append(item)
                if candidate=='extend_profit':
                    largest = joined.loc[joined.cycle_log_difference.abs().nlargest(12).index].copy()
                    largest['selection']='Top 12 absolute realized cycle-log differences; descriptive examples only, no deletion or counterfactual account.'
                    episodes.append(largest)
    for variant, t in tables.items():
        previous=100000.
        for year, part in t['account_daily'].groupby(t['account_daily'].index.year):
            values=np.r_[previous,part.equity.to_numpy(float)]
            annual.append(dict(variant=variant,year=int(year),start_nav=previous,end_nav=float(values[-1]),
                               return_=float(values[-1]/previous-1),maximum_drawdown=float(np.max(1-values/np.maximum.accumulate(values)))))
            previous=float(values[-1])
    joined_all=pd.concat(pairs,ignore_index=True)
    source_state=EX/'others/state_diagnostics_v2.json'
    diagnostic=json.loads(source_state.read_text(encoding='utf-8'))
    members_path=EX/'others/state_diagnostics_v2_members.csv'
    assert sha256(members_path.read_bytes()).hexdigest()==diagnostic['outputs'][members_path.name]
    members=pd.read_csv(members_path)
    profit=joined_all.loc[joined_all.comparison.eq('extend_profit_minus_baseline_H3')&joined_all.window.eq('ALL')].copy()
    bridge=members.merge(profit[['entry_date','category','both_closed','position_return_difference','cycle_log_difference',
                                'exit_or_mark_date_right','position_return_right']],on='entry_date',how='left',validate='one_to_one')
    bridge['original_P_fixed_increment']=bridge.extension_increment.where(bridge.P.eq(True),0.)
    paired=bridge.loc[bridge.label_status.eq('OBSERVED')]
    common=paired.loc[paired.category.eq('matched')&paired.both_closed]
    expected_exit=np.where(common.P.eq(True),common.extended_actual_exit,common.original_actual_exit)
    assert np.array_equal(common.exit_or_mark_date_right.to_numpy(),expected_exit)
    assert np.allclose(common.position_return_difference,common.original_P_fixed_increment,rtol=0,atol=1e-12)
    bridge_summary=[]
    for cohort, part in core.scopes(paired):
        for cat in ('ALL','matched','left_only'):
            p=part if cat=='ALL' else part.loc[part.category.eq(cat)]
            bridge_summary.append(dict(entry_cohort=cohort,path_category=cat,original_closed_entries=len(p),
                                       P_selected=int(p.P.eq(True).sum()),
                                       fixed_original_entry_increment=core.distribution(p.original_P_fixed_increment),
                                       note='Original H3 entry universe; hypothetical paired labels remain positive even if those entries are absent in the actual conditional account.'))
    outputs={'trades':pd.concat(all_cycles,ignore_index=True),'matches':joined_all,
             'summary':pd.json_normalize(summaries),'decomposition':pd.json_normalize(decompositions),
             'reconciliation':pd.DataFrame(recon),'annual_nav':pd.DataFrame(annual),
             'profit_episodes':pd.concat(episodes,ignore_index=True),'profit_bridge':bridge,
             'profit_bridge_summary':pd.json_normalize(bridge_summary)}
    hashes={}
    for name,value in outputs.items():
        path=EX/f'others/path_diagnostics_{name}.csv'
        if path.exists():
            raise RuntimeError('Preserve '+path.name)
        value.to_csv(path,index=False,lineterminator='\n')
        hashes[path.name]=sha256(path.read_bytes()).hexdigest()
    result=dict(status='PASS',source_calls=0,new_account_runs=0,sources=selected,
                script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                imported_cycle_source_sha256=sha256(PRIOR.read_bytes()).hexdigest(),
                comparison_manifest_sha256=sha256(manifest.read_bytes()).hexdigest(),
                source_diagnostic_sha256=sha256(source_state.read_bytes()).hexdigest(),
                method={'direction':'Left baseline, right new conditional account; difference is candidate minus baseline.',
                        'matching':'Unique actual entry date; matched execution entry prices are asserted identical.',
                        'cash_cycles':'Actual buy outlay and net sale proceeds plus actual residual cash reconstruct each wealth cycle. Product equals actual terminal NAV.',
                        'open':'Mark actual remaining quantity at the same closing price used in the account; no hypothetical sale fee.',
                        'windows':'ALL through 2026-10-15; WITHOUT2026 truly truncates at 2025-12-31 and marks then-open positions at that closing NAV.',
                        'years':'Entry-year cohorts for path decomposition; separate natural-year NAV statistics. Cohort contributions are not annual account profit.',
                        'interpretation':'Matched+left-only+right-only log terms add to actual log NAV difference. Position percentages do not add to account return. Cash-lot effects can have either sign.',
                        'causality':'Historical attribution, not independent causal effects. Position duration changes later entry availability; residual cash depends on prior path.',
                        'bridge':'Original H3 paired diagnostic kept all original entries. Actual conditional account cannot necessarily take those entries. Matched actual exit and paired prediction verified for every both-closed original entry.',
                        'examples':'Largest absolute log differences selected only to explain realized episodes; no retrospective deletion or new strategy.'},
                checks=dict(cycle_reconciliations=len(recon),
                            max_absolute_cycle_return_error=max(r['absolute_reconciliation_error'] for r in recon),
                            full_window_pair_decompositions=16,
                            max_absolute_decomposition_log_error=max(r.get('absolute_decomposition_error',0) for r in decompositions),
                            profit_matched_closed_labels_reproduced=len(common),
                            all_six_formal_evidence_hashes_verified=True,all_matched_entry_prices_identical=True),
                reconciliation=recon,decompositions=decompositions,profit_bridge_summary=bridge_summary,
                annual_nav=annual,outputs=hashes)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','checks':result['checks'],
                      'profit':[r for r in decompositions if r['candidate']=='extend_profit' and r['entry_cohort']=='ALL'],
                      'bridge':[r for r in bridge_summary if r['entry_cohort']=='ALL']},indent=2))


if __name__=='__main__':
    main()
