import json
from pathlib import Path
import sys

root=Path.cwd()
number=int(sys.argv[1])
work=root/f'research/S018/experiments/EX{number:03d}_20261104'
record=json.loads((work/'others/results.json').read_text(encoding='utf-8'))
accounts=record['accounts']
passed=[(k,v) for k,v in accounts.items() if all(v['gates'].values())]
passed.sort(key=lambda kv:kv[1]['candidate']['calmar'],reverse=True)
print('TOTAL',len(accounts),'PASS',len(passed))
for k,v in passed[:15]:
    m=v['candidate']
    print(k,v['config'],{z:m[z] for z in ['annual','dd','calmar','closed','median','coverage']})
print('BEST_PER_SHARE')
for share in dict.fromkeys(v['config']['common_share'] for v in accounts.values()):
    group=[(k,v) for k,v in accounts.items() if v['config']['common_share']==share]
    best=max(group,key=lambda kv:kv[1]['candidate']['calmar'])
    feasible=[(k,v) for k,v in group if all(v['gates'].values())]
    print(share,'overall',best[0],round(best[1]['candidate']['calmar'],4),best[1]['gates'],
        'feasible',max(feasible,key=lambda kv:kv[1]['candidate']['calmar'])[0] if feasible else None)
lines=['|配置|共同贡献门槛|首次检查|最长持有|净年化|回撤|净卡玛|闭合|60日中位|覆盖|全部达标|',
       '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
for k,v in accounts.items():
    p,m=v['config'],v['candidate']
    lines.append(f"|{k}|{p['common_share']}|{p['review_after']}|{p['max_hold']}|{m['annual']:.2%}|{m['dd']:.2%}|{m['calmar']:.3f}|{m['closed']}|{m['median']:g}|{m['coverage']:.2%}|{'是' if all(v['gates'].values()) else '否'}|")
(root/f'.tmp/s018_stage3/table{number}.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
summary={'configurations':len(accounts),'passed':[k for k,v in passed],
         'objective':'net annualized return / maximum daily equity drawdown',
         'all_original_gates_preserved':True}
if number==50:
    from czsc_trader import research_tools as d
    from czsc_trader.research_tools.equity_replay import materialize_equity
    old=json.loads((root/'research/S018/experiments/EX045_20261104/others/results.json').read_text(encoding='utf-8'))['accounts']
    def run(row):
        ref=d.EvidenceRef.from_dict(row['account_ref']); path=ref.resolve(root)
        return materialize_equity(path.read_bytes(),lambda v:(path.parent/(v['sha256']+'.json')).read_bytes()).payload['runs']['candidate']
    checks={}
    for new_id,old_id in [('C8004','C7501'),('C8031','C7502')]:
        new,prior=run(accounts[new_id]),run(old[old_id])
        checked=[]
        for field in ['fills','account_daily','trades','corporate_actions']:
            if field not in new or field not in prior:
                continue
            economic=lambda rows:[{k:v for k,v in row.items() if not k.endswith('_id')} for row in rows]
            assert economic(new[field])==economic(prior[field]),(new_id,field)
            checked.append(field)
        assert accounts[new_id]['candidate']==old[old_id]['candidate']
        checks[new_id]={'original':old_id,'economic_rows_exact':checked,'metrics_exact':True}
    summary['controls']=checks
(work/'others/analysis_search.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
