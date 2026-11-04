from pathlib import Path
from hashlib import sha256
import json
import statistics
from czsc_trader.research_tools.equity_replay import materialize_equity


def main():
    w=Path(__file__).resolve().parents[1];family=w.parents[1]
    records=json.loads((w/'others/results.json').read_text(encoding='utf-8'))['accounts']
    output={}
    for key in ['C7419','C7421','C7422','C7423']:
        a=records[key];ref=a['account_ref'];p=family/'assets/evidence'/ref['experiment']['experiment_id']/ref['evidence_id']
        raw=p.read_bytes();assert sha256(raw).hexdigest()==ref['sha256']
        v=materialize_equity(raw,lambda x:(p.parent/(x['sha256']+'.json')).read_bytes()).payload
        run=v['runs']['candidate'];ready=[];october=[]
        for d in run['decisions']:
            facts={f['key']:f['text'] for f in d['explanation']['basis']}
            if facts.get('forecast')!='not_ready':ready.append(d['execution_start'][:10])
            if '2026-10-01'<=d['execution_start'][:10]<='2026-10-16':
                october.append({'execution':d['execution_start'][:10],'observed_through':d['observed_through'],
                    'side':d.get('side'),'target':d['target'],'judgment':d['explanation']['judgment'],'facts':facts})
        sessions=[r['session'] for r in run['account_daily']]
        first=sessions.index(min(ready))
        closed_dates=[t['exit_at'][:10] for t in run['trades'] if t['status']=='CLOSED']
        counts=[]
        for last in range(first+59,len(sessions)):
            start=last-59;counts.append(sum(sessions[start]<=d<=sessions[last] for d in closed_dates))
        output[key]={'first_ready_execution':min(ready),'ready_only_full_60_windows':len(counts),
            'diagnostic_median':statistics.median(counts),'diagnostic_coverage':sum(n>=3 for n in counts)/len(counts),
            'october_decisions':october,
            'limit':'准备期后诊断不替代原全开发池频率硬门，不更改账户或候选资格。'}
    (w/'others/analysis_readiness_october.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:{a:v[a] for a in ['first_ready_execution','diagnostic_median','diagnostic_coverage']} for k,v in output.items()})


if __name__=='__main__':main()
