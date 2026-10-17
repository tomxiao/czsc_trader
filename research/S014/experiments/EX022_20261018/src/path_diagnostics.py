"""Paired initial-time sensitivity; exact account-cycle reconciliation, no new replay."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
PRIOR=EX.parent/'EX018_20261017/src/account_diagnostics.py'
spec=importlib.util.spec_from_file_location('phase_account_cycles',PRIOR)
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
BASES=('repeated_H10','support_entry_H10')

def main():
    out=EX/'others/path_diagnostics.json'
    if out.exists():raise RuntimeError('Preserve previous diagnosis')
    requests.sessions.Session.request=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('Offline only'))
    records=json.loads((EX/'others/comparison_accounts.json').read_text(encoding='utf-8'))['records']
    comparison=json.loads((EX/'others/comparison.json').read_text(encoding='utf-8'))
    assert len(records)==22 and all(r['status']=='SUCCEEDED' for r in records)
    tables={r['variant']:core.load(r) for r in records};recon=[];paired=[];dispersion=[];cohorts=[];paths=[]
    for window,cutoff in [('ALL',pd.Timestamp('2026-10-15')),('WITHOUT2026',pd.Timestamp('2025-12-31'))]:
        current={};checks={}
        for v,t in tables.items():
            c,r=core.cycles(t,cutoff,v);recon.append(r);current[v]=c;checks[v]=r
        for offset in range(11):
            a,b=[f'{base}_delay{offset}' for base in BASES]
            matched,s=core.compare(current[a],current[b],f'B_minus_A_delay{offset}',window)
            cohorts.extend(s)
            delta=checks[b]['actual_log']-checks[a]['actual_log']
            error=abs(float(matched.cycle_log_difference.sum())-delta);assert error<1e-10
            paired.append({'window':window,'delay':offset,'A_return':checks[a]['actual_return'],'B_return':checks[b]['actual_return'],
                'return_difference':checks[b]['actual_return']-checks[a]['actual_return'],
                'cycle_log_contributions':{g:float(matched.loc[matched.category.eq(g),'cycle_log_difference'].sum()) for g in ('matched','left_only','right_only')},
                'matched_entry_count':int(matched.category.eq('matched').sum()),'nav_log_difference':delta,'absolute_decomposition_error':error})
        for base in BASES:
            values=[checks[f'{base}_delay{i}']['actual_return'] for i in range(11)]
            dispersion.append({'window':window,'base':base,'min_return':min(values),'max_return':max(values),'median_return':float(np.median(values)),'mean_return':float(np.mean(values))})
    # Compare executed BUY/SELL dates, ignoring quantities that differ with residual cash.
    for base in BASES:
        reference=tables[f'{base}_delay0']['fills']
        original={(pd.Timestamp(r.fill_time).normalize(),str(r.side)) for r in reference.itertuples()}
        for offset in range(11):
            t=tables[f'{base}_delay{offset}'];f=t['fills']
            actual={(pd.Timestamp(r.fill_time).normalize(),str(r.side)) for r in f.itertuples()}
            different=original.symmetric_difference(actual)
            paths.append({'base':base,'delay':offset,'first_actual_buy':f.loc[f.side.eq('BUY'),'fill_time'].min().date().isoformat(),
                'different_execution_date_side_events':len(different),
                'last_different_execution_date':max(d for d,s in different).date().isoformat() if different else None,
                'common_events':len(original.intersection(actual))})
    years=pd.DataFrame(comparison['annual']);year_pairs=[]
    for offset in range(11):
        a=years.loc[years.variant.eq(f'repeated_H10_delay{offset}')].set_index('year')
        b=years.loc[years.variant.eq(f'support_entry_H10_delay{offset}')].set_index('year')
        for year in range(2020,2027):
            aa,bb=a.loc[year],b.loc[year]
            year_pairs.append({'delay':offset,'year':year,'A_return':aa['return'],'B_return':bb['return'],
                'return_difference':bb['return']-aa['return'],'A_drawdown':aa.max_drawdown,'B_drawdown':bb.max_drawdown,
                'drawdown_difference':bb.max_drawdown-aa.max_drawdown,'A_return_pass':bool(aa.return_pass),'B_return_pass':bool(bb.return_pass),
                'A_drawdown_pass':bool(aa.drawdown_pass),'B_drawdown_pass':bool(bb.drawdown_pass)})
    outputs={}
    for name,frame in [('paired',pd.DataFrame(paired)),('annual_paired',pd.DataFrame(year_pairs)),('execution_dates',pd.DataFrame(paths)),('reconciliation',pd.DataFrame(recon))]:
        p=EX/f'others/timing_{name}.csv';frame.to_csv(p,index=False);outputs[p.name]=sha256(p.read_bytes()).hexdigest()
    result={'status':'PASS','new_accounts':0,'new_upstream_calls':0,'source_records':records,'reconciliations':recon,
        'paired_controls':paired,'dispersion':dispersion,'annual_paired':year_pairs,'execution_dates':paths,'cohort_diagnostics':cohorts,'outputs':outputs,
        'source_helper':{'path':PRIOR.relative_to(ROOT).as_posix(),'sha256':sha256(PRIOR.read_bytes()).hexdigest()},
        'all_targets_pass_count':comparison['all_targets_pass_count'],
        'limits':'All11delays predetermined and dependent on same seen prices. No bestdelay selection.11represents idealH10+reentrycycle, not exhaustive phases after failedorders. Same execution dates do not imply identical cash or NAV. Cohort path sums are arithmetic, not independent causal attribution. All original annual/frequency gates remain exact; this sensitivity is not a new hard acceptance threshold.'}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('EX022_TIMING_DIAGNOSTICS_PASS',len(recon),'reconciliations')

if __name__=='__main__':main()
