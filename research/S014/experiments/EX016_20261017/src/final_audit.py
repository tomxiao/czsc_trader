"""Reconcile every annual aggregate, bootstrap interval and published audit bytes."""
import json
from hashlib import sha256
import numpy as np
import pandas as pd
from study import EX,ROOT,RUN,inputs,strict
from annual_followup import interval

def main():
    target=EX/'others/final_audit.json'
    if target.exists():raise RuntimeError('Preserve final audit')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'));audit=read(EX/'others/audit.json')
    for x in audit['manifest']:assert sha256((ROOT/x['path']).read_bytes()).hexdigest()==x['sha256']
    checks=[]
    def check(name,value):
        assert value,name
        checks.append(name)
    _,dates,*_=inputs();annual=pd.read_csv(RUN/'annual_observations.csv');rolling=pd.read_csv(RUN/'observations.csv')
    for name,table in [('annual',pd.read_csv(EX/'others/annual_extension.csv')),('rolling',pd.read_csv(EX/'others/annual.csv'))]:
        for r in table.itertuples():
            g=annual if name=='annual' else rolling.loc[rolling.window.eq(r.window)]
            if r.scope=='WITHOUT2026':g=g.loc[g.year.ne(2026)]
            elif r.scope=='EARLY2020_2022':g=g.loc[g.year.le(2022)]
            elif r.scope in ('OLD2023_2026','OVERLAP2023'):g=g.loc[g.year.ge(2023)]
            elif r.scope!='ALL':g=g.loc[g.year.eq(int(r.scope))]
            a=g.loc[g.high];b=g.loc[~g.high];no=strict(g);na=no.loc[no.high];nb=no.loc[~no.high]
            expected=[len(a),len(b),a.net_return.mean(),b.net_return.mean(),a.net_return.mean()-b.net_return.mean(),a.extension.mean(),b.extension.mean(),len(no),na.net_return.mean()-nb.net_return.mean(),nb.extension.mean()]
            actual=[r.high_n,r.low_n,r.high_net,r.low_net,r.difference,r.high_extension,r.low_extension,r.nonoverlap_n,r.nonoverlap_diff,r.nonoverlap_low_extension]
            check(name+'/'+str(getattr(r,'window','annual'))+'/'+r.scope,np.allclose(expected,actual,rtol=0,atol=1e-12,equal_nan=True))
    result=read(EX/'others/annual_followup.json');recomputed=interval(annual,dates,20)+interval(annual,dates,60)
    check('both block interval reproduction',all(a['block']==b['block'] and a['metric']==b['metric'] and np.allclose([a[k] for k in ('point','low','high','sim_low','sim_high')],[b[k] for k in ('point','low','high','sim_low','sim_high')],rtol=0,atol=1e-12) for a,b in zip(result['intervals'],recomputed)))
    audited=pd.read_csv(EX/'others/audited_clusters.csv');saved=pd.read_csv(EX/'others/annual_clusters.csv').query("scope == 'ALL'")
    for r in saved.itertuples():
        q=audited.loc[(audited.calibration=='annual')&(audited.high==(r.group=='high'))&(audited.metric==r.value)].iloc[0]
        check('cluster '+r.group+'/'+r.value,np.allclose([q.clusters,q.equal_mean,q.leave_min,q.leave_max],[r.clusters,r.cluster_equal,r.leave_min,r.leave_max],rtol=0,atol=1e-12))
    paths=[*EX.rglob('*.py'),*EX.rglob('*.json'),*EX.rglob('*.csv'),*RUN.glob('*.csv')]
    manifest=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted(set(paths)) if p.name!='final_audit.json']
    target.write_text(json.dumps({'status':'PASS','prior_check_count':audit['check_count'],'additional_checks':checks,'total_checks':audit['check_count']+len(checks),'manifest':manifest,'source_calls':0},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('FINAL_PASS',audit['check_count']+len(checks))

if __name__=='__main__':main()
