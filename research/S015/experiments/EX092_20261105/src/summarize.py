from plan_context import *
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity

def main():
    rows=[read(OUT/f'result_C9820_{w}_{s}.json') for w,s in [('full','STANDARD'),('s011_common','STANDARD'),('full','FEE_X2')]]+read(OUT/'bound_results.json')['accounts']
    result=[]
    for item in rows:
        ref=EvidenceRef.from_dict(item['reference']);p=ref.resolve(ROOT)
        payload=materialize_equity(p.read_bytes(),lambda r:(p.parent/(r['sha256']+'.json')).read_bytes()).payload
        run=payload['runs']['candidate'];oldref=EvidenceRef.from_dict(item['old_reference'])
        old=next(r for r in read(oldref.resolve(ROOT))['runs'] if r['window_id']==item['window'])
        a=old['replay_evidence']['decisions'];b=run['decisions'];assert len(a)==len(b)
        mismatches=[]
        for i,(o,n) in enumerate(zip(a,b)):
            basis={v['key']:v['text'] for v in n['explanation']['basis']}
            if bool(o['target_position'])!=bool(n['target']) or o['signal_date'][:10]!=basis['signal_day'] or bool(o['entry_signal'])!=(basis['entry_signal']=='True') or bool(o['exit_signal'])!=(basis['exit_signal']=='True'):mismatches.append(i)
        assert not mismatches
        scenario=item.get('scenario','STANDARD');fee=.002 if scenario=='FEE_X2' else .001
        assert all(abs(f['fees']-f['quantity']*f['price']*fee)<1e-8 for f in run['fills'])
        m=run['metrics'];om=old['replay_evidence']['metrics']
        result.append({'candidate_id':item['candidate_id'],'window':item['window'],'scenario':scenario,'reference':item['reference'],'signal_intent_status':'PASS','signal_count':len(a),'fees_verified':fee,'fills':len(run['fills']),'annualized_return':m['annualized_return'],'max_drawdown':m['daily_max_drawdown'],'total_return':m['total_return'],'frequency_median':m['rolling_60_closed_cycle_median'],'old_annualized_return':(1+om['return'])**(252/len(a))-1,'old_max_drawdown':abs(om['max_drawdown']),'buyhold_annualized_return':payload['runs']['buy_hold']['metrics']['annualized_return'],'buyhold_max_drawdown':payload['runs']['buy_hold']['metrics']['daily_max_drawdown']})
    save(OUT/'summary.json',{'accounts':result,'statistics':read(OUT/'bound_results.json')['statistics']})
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
