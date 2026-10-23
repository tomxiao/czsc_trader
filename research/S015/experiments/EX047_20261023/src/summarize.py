"""Read-only arithmetic across the stage-three searched accounts; no new runs."""
import json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parents[1]
BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def main():
    rows=[];sources={};counts=[]
    for n in range(42,48):
        h=BASE/f'EX{n:03d}_20261023';p=h/'others/results.json';r=read(p)
        sources[p.relative_to(BASE).as_posix()]=sha256(p.read_bytes()).hexdigest()
        counts.append({'experiment':h.name,**{k:r[k] for k in ('new_configurations','account_scenarios','technical_precheck_extra_scenarios','qualified_centers')}})
        for x in r['rows']:
            x={**x,'experiment':h.name};x['parameters']={**x['parameters'],'exit_rule':x['parameters'].get('exit_rule','fixed')};rows.append(x)
    identity=lambda r:(r['parameters']['family'],r['parameters']['mode'],r['parameters']['exit_rule'],r['parameters']['hold'])
    assert len(rows)==159 and len(set(map(identity,rows)))==159
    assert {(f,m,e,h) for f in ('A','B') for m in ('path','risk','and') for e in ('fixed','permission') for h in range(1,10)}.issubset(set(map(identity,rows)))
    boundary=read(HERE/'others/runtime_checks.json');assert boundary['status']=='PASS'
    maxima=boundary['maximum_permission_runs']
    fixed={(f,m,'fixed',h) for f in ('A','B') for m in ('path','risk','and') for h in range(1,10)}
    permission={(key.split('/')[0],key.split('/')[1],'permission',h) for key,M in maxima.items() for h in range(1,M+1)}
    redundant={('A','and','permission',9),('B','path','permission',30),('B','and','permission',15),('B','and','permission',30)}
    assert len(fixed)==54 and len(permission)==101 and set(map(identity,rows))==fixed|permission|redundant
    assert sum(x['account_scenarios'] for x in counts)==318 and sum(x['technical_precheck_extra_scenarios'] for x in counts)==4
    flat=[{'experiment':r['experiment'],'candidate':r['candidate_id'],**r['parameters'],**r['runs']['full'],'common_return':r['runs']['s011_common']['net_return'],'common_dd':r['runs']['s011_common']['dd'],'joint_pass':r['both_center_pass']} for r in rows]
    pd.DataFrame(flat).drop(columns=['checks']).to_csv(HERE/'others/all_centers.csv',index=False)
    best=max(rows,key=lambda r:r['runs']['full']['net_return']);low=min(rows,key=lambda r:r['runs']['full']['dd'])
    def concise(r):
        f=r['runs']['full'];c=r['runs']['s011_common']
        return {'experiment':r['experiment'],'candidate':r['candidate_id'],'parameters':r['parameters'],'net_return':f['net_return'],'dd':f['dd'],'cagr':f['cagr'],'closed':f['closed'],'frequency_median':f['frequency_median'],'frequency_good':f['frequency_good'],'full_pass':f['center_pass'],'common_return_pass':c['return_superior'],'common_dd_pass':c['dd_superior'],'joint_pass':r['both_center_pass'],'evidence':r['evidence']}
    frontier=[]
    for r in rows:
        f=r['runs']['full']
        if not any(s['runs']['full']['net_return']>=f['net_return'] and s['runs']['full']['dd']<=f['dd'] and (s['runs']['full']['net_return']>f['net_return'] or s['runs']['full']['dd']<f['dd']) for s in rows):frontier.append(concise(r))
    groups=[]
    for fam in ('A','B'):
        for mode in ('path','risk','and'):
            for ex in ('fixed','permission'):
                rr=[r for r in rows if identity(r)[:3]==(fam,mode,ex)]
                groups.append({'family':fam,'mode':mode,'exit_rule':ex,'count':len(rr),'best_return':concise(max(rr,key=lambda r:r['runs']['full']['net_return'])),'lowest_dd':concise(min(rr,key=lambda r:r['runs']['full']['dd']))})
    selected={r['candidate_id']:r for r in rows if r['runs']['full']['center_pass']}
    selected.update({best['candidate_id']:best,low['candidate_id']:low})
    stability=[]
    for cid,r in selected.items():
        p=BASE/r['experiment']/f'others/{cid}_full_account_daily.csv';a=pd.read_csv(p,parse_dates=['date']);sources[p.relative_to(BASE).as_posix()]=sha256(p.read_bytes()).hexdigest()
        eq=np.r_[100000.,a.equity.to_numpy()];peak=np.maximum.accumulate(eq)
        periods=[]
        for year in (2025,2026):
            ix=np.where(a.date.dt.year.eq(year))[0];start,end=int(ix[0]),int(ix[-1]);v=eq[start:end+2]
            periods.append({'year':year,'sessions':len(ix),'start':str(a.date.iloc[start].date()),'end':str(a.date.iloc[end].date()),'return':float(v[-1]/v[0]-1),'local_peak_dd':float(np.max(1-v/np.maximum.accumulate(v))),'inherited_peak_dd':float(np.max(1-eq[start+1:end+2]/peak[start+1:end+2]))})
        rolling=[]
        for start in range(0,len(a)-252+1,21):
            v=eq[start:start+253];rolling.append({'start':str(a.date.iloc[start].date()),'end':str(a.date.iloc[start+251].date()),'return':float(v[-1]/v[0]-1),'local_peak_dd':float(np.max(1-v/np.maximum.accumulate(v)))})
        stability.append({'candidate':cid,'years':periods,'rolling252_step21':rolling})
    out={'status':'COMPLETED_DESCRIPTIVE_ARITHMETIC','counts':counts,'total_configurations':len(rows),'standard_accounts':sum(x['account_scenarios'] for x in counts),'technical_repeat_accounts':sum(x['technical_precheck_extra_scenarios'] for x in counts),'full_center_pass':sum(r['runs']['full']['center_pass'] for r in rows),'common_return_pass':sum(r['runs']['s011_common']['return_superior'] for r in rows),'common_dd_pass':sum(r['runs']['s011_common']['dd_superior'] for r in rows),'joint_pass':sum(r['both_center_pass'] for r in rows),'best_return':concise(best),'lowest_dd':concise(low),'return_dd_frontier':frontier,'family_summary':groups,'full_center_candidates':[concise(r) for r in rows if r['runs']['full']['center_pass']],'time_diagnostics':stability,'source_hashes':sources,'limitations':'Repeatedly observed development sample; 159 configurations include exact duplicate intention paths in some cases and are not 159 independent signals. Time slices inherit original equity and positions; no independent recapitalization, significance test, stage-four perturbation or fee stress. Local peak and inherited peak drawdowns are labelled separately; partial calendar years not annualized. Frontier ignores frequency and is descriptive, not candidate qualification.'}
    out['finite_domain']={'fixed_representatives':54,'permission_representatives':101,'above_bound_redundant_identities':4,'maximum_permission_runs':maxima,'scope':'Fixed model, threshold, full exposure, canonical historical input only; no claim of independent information or distinct behavior for every representative.'}
    out['source_hashes']['EX047_20261023/others/runtime_checks.json']=sha256((HERE/'others/runtime_checks.json').read_bytes()).hexdigest()
    save(HERE/'others/search_summary.json',out)
    print(json.dumps({k:out[k] for k in ('total_configurations','standard_accounts','full_center_pass','common_return_pass','common_dd_pass','joint_pass','best_return','lowest_dd')},ensure_ascii=False))
if __name__=='__main__':main()
