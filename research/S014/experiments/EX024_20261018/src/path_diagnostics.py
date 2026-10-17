"""Authenticate and decompose first-break conditional account paths, without new replay."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
PRIOR=EX.parent/'EX018_20261017/src/account_diagnostics.py'
spec=importlib.util.spec_from_file_location('support_account_cycles',PRIOR)
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
PAIRS=(('support_entry_H10', 'support_first_profit_exit_H10'), ('support_entry_H10', 'support_first_nonprofit_exit_H10'), ('support_exit_reserve_H10', 'support_first_profit_exit_H10'), ('support_exit_reserve_H10', 'support_first_nonprofit_exit_H10'), ('support_first_profit_exit_H10', 'support_first_nonprofit_exit_H10'))


def main():
    out=EX/'others/path_diagnostics.json'
    if out.exists():raise RuntimeError('Preserve existing diagnosis')
    requests.sessions.Session.request=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('Offline only'))
    records=json.loads((EX/'others/comparison_accounts.json').read_text(encoding='utf-8'))['records']
    assert len(records)==4 and all(r['status']=='SUCCEEDED' for r in records)
    tables={r['variant']:core.load(r) for r in records}
    recon=[];cycles=[];contrasts=[];matches=[];decompositions=[];exposure=[]
    for window,cutoff in [('ALL',pd.Timestamp('2026-10-15')),('WITHOUT2026',pd.Timestamp('2025-12-31'))]:
        current={};checked={}
        for v,t in tables.items():
            c,r=core.cycles(t,cutoff,v);c['window']=window
            cycles.append(c);recon.append(r);current[v]=c;checked[v]=r
            d=t['account_daily'].loc[:cutoff];f=t['fills'].loc[t['fills'].fill_time.dt.normalize().le(cutoff)]
            exposure.append({'window':window,'variant':v,'held_close_sessions':int(d.quantity.gt(0).sum()),
                'flat_close_sessions':int(d.quantity.eq(0).sum()),'fees':float(f.fees.sum()),
                'closed':r['closed'],'open':r['marked_open'],'return':r['actual_return']})
        for a,b in PAIRS:
            paired,s=core.compare(current[a],current[b],b+'_minus_'+a,window)
            matches.append(paired);contrasts.extend(s)
            for cohort,part in core.scopes(paired):
                contributions={c:float(part.loc[part.category.eq(c),'cycle_log_difference'].sum()) for c in ('matched','left_only','right_only')}
                r={'window':window,'entry_cohort':cohort,'baseline':a,'changed':b,'cycle_log_contributions':contributions,
                   'counts':{c:int(part.category.eq(c).sum()) for c in contributions},'total_cycle_log_difference':float(part.cycle_log_difference.sum())}
                if cohort=='ALL':
                    actual=checked[b]['actual_log']-checked[a]['actual_log'];error=abs(actual-r['total_cycle_log_difference'])
                    assert error<1e-10
                    r.update(actual_nav_log_difference=actual,absolute_decomposition_error=error)
                decompositions.append(r)
    outputs={}
    for name,frame in [('cycles',pd.concat(cycles)),('matches',pd.concat(matches)),('exposure',pd.DataFrame(exposure)),('reconciliation',pd.DataFrame(recon))]:
        p=EX/f'others/path_{name}.csv';frame.to_csv(p,index=False,lineterminator="\n");outputs[p.name]=sha256(p.read_bytes()).hexdigest()
    result={'status':'PASS','new_accounts':0,'new_upstream_calls':0,'source_records':records,
        'core_source':{'path':PRIOR.relative_to(ROOT).as_posix(),'sha256':sha256(PRIOR.read_bytes()).hexdigest()},
        'reconciliations':recon,'decompositions':decompositions,'cohort_diagnostics':contrasts,'exposure':exposure,'outputs':outputs,
        'limits':'Actual matched/unique trade paths provide arithmetic explanation, not independent causal effects. Entry-year cohorts are not annual NAV returns. All four share the same60sessionstartup. Complementary P-state choices can alter actual sale and later entry paths; they are not additive or independent accounts. Cutoff-held trades marked at cutoff close without an invented exit fee. No future dates drive a decision.'}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('EX024_PATH_PASS',len(recon),'reconciliations')

if __name__=='__main__':main()
