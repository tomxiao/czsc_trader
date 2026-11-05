"""Compare saved economic facts and exercise the current public window reader."""
from pathlib import Path
import json
from hashlib import sha256
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity
from czsc_trader.application import RepositoryContext, project_selection_window_facts
from czsc_trader.research_tools.selection_stability import SelectionWindowSource,SelectionWindowFactsRequest,SelectionProjectionBudget
from strategy_evaluator.research_models import AssessmentCandidate
from strategy_evaluator.selection_models import SelectionWindow,SelectionWindowPair,SelectionWindowPlan
from strategy_runtime import canonical_sha256,equity_source_hash

ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]
def read(p): return json.loads(p.read_text(encoding='utf-8'))

def main():
    refs=read(ROOT/'research/S015/experiments/EX087_20261105/others/input_sources.json')['old_accounts']
    result=[]
    for item in read(HOME/'others/results.json')['accounts']:
        oldref=EvidenceRef.from_dict(refs[item['scenario'].lower()])
        oldbytes=oldref.resolve(ROOT).read_bytes()
        assert sha256(oldbytes).hexdigest()==oldref.sha256
        oldrun=json.loads(oldbytes)['runs'][0]
        old=oldrun['replay_evidence']
        newref=EvidenceRef.from_dict(item['reference']); path=newref.resolve(ROOT)
        content=path.read_bytes(); assert sha256(content).hexdigest()==newref.sha256
        full=materialize_equity(content,lambda r:(path.parent/(r['sha256']+'.json')).read_bytes()).payload
        new=full['runs']['candidate']
        signals=oldrun['signals']['data']
        assert len(signals)==len(new['decisions'])==434
        signal_differences=[]
        for a,b in zip(signals,new['decisions'],strict=True):
            day=pd.Timestamp(b['observed_through']).tz_convert('Asia/Shanghai').date().isoformat()
            if a['signal_date'][:10]!=day or float(a['target_position'])!=b['target']:
                signal_differences.append({'old':a,'new':b})
        assert not signal_differences
        assert len(old['fills'])==len(new['fills'])==108
        numeric={k:0. for k in ('price','quantity','fees')}
        for a,b in zip(old['fills'],new['fills'],strict=True):
            assert a['side']==b['side']
            assert a['fill_time'][:10]==pd.Timestamp(b['interval_start']).tz_convert('Asia/Shanghai').date().isoformat()
            for k in numeric: numeric[k]=max(numeric[k],abs(a[k]-b[k]))
        accounts={k:0. for k in ('cash','quantity','close','equity')}
        assert len(old['account_daily'])==len(new['account_daily'])==434
        for a,b in zip(old['account_daily'],new['account_daily'],strict=True):
            assert a['date'][:10]==b['session']
            for k in accounts: accounts[k]=max(accounts[k],abs(a[k]-b[k]))
        # Float cash accumulation may differ by sub-nanoyuan rounding only.
        assert max(numeric.values())<1e-8 and max(accounts.values())<1e-8,(numeric,accounts)
        ob=oldrun['buyhold']['account_daily']['data']; nb=full['runs']['buy_hold']['account_daily']
        assert len(ob)==len(nb)==434
        benchmark_delta=max(abs(a['equity']-b['equity']) for a,b in zip(ob,nb,strict=True))
        assert benchmark_delta<1e-8,benchmark_delta
        m=new['metrics']; annual_old=(1+old['metrics']['return'])**(252/434)-1
        row={'scenario':item['scenario'],'old_source':oldref.to_dict(),'new_source':newref.to_dict(),
            'signal_count':434,'signal_difference_count':0,'fills':108,'max_fill_differences':numeric,
            'max_daily_account_differences':accounts,'max_benchmark_equity_difference':benchmark_delta,
            'old':{'return':old['metrics']['return'],'annual':annual_old,'drawdown':-old['metrics']['max_drawdown'],
                   'closed_cycles':old['metrics']['closed_trades'],'ending_equity':old['account_daily'][-1]['equity']},
            'new':{'return':m['total_return'],'annual':m['annualized_return'],'drawdown':m['daily_max_drawdown'],
                   'closed_cycles':m['closed_cycles'],'ending_equity':new['account_daily'][-1]['equity'],
                   'rolling60_median':m['rolling_60_closed_cycle_median']}}
        result.append(row)
        if item['scenario']=='STANDARD':
            calendar=tuple(x['session'] for x in new['account_daily'])
            source_doc=read(path.parent/(full['candidate_ref']['sha256']+'.json'))
            candidate=AssessmentCandidate('S015-C9802',source_doc['owner']['content_sha256'])
            standard_ref=newref
    # A capability probe, not a design or verdict of selection stability.
    plan=SelectionWindowPlan(calendar,canonical_sha256(calendar),(SelectionWindowPair('migration-readability',
        SelectionWindow('first252',calendar[0],calendar[251]),SelectionWindow('next126',calendar[252],calendar[377])),),
        ('Migration readability probe only; does not run candidate selection or constitute stage-four acceptance.',))
    projected=project_selection_window_facts(RepositoryContext.discover(ROOT),SelectionWindowFactsRequest(
        (SelectionWindowSource(candidate,standard_ref),),plan,60,3,SelectionProjectionBudget(4,100000000,100000000)))
    assert projected.status.value=='COMPLETE' and all(x.status.value=='COMPLETE' for x in projected.facts)
    assert len(projected.facts)==4
    output={'status':'ECONOMIC_EQUIVALENCE_WITHIN_FLOAT_PRECISION','absolute_numeric_tolerance':1e-8,
        'scope':'C9700 full434 standard and fee_x2; source identities/time precision intentionally differ.',
        'accounts':result,'current_selection_reader':{'status':projected.status.value,'facts':len(projected.facts),'stats':projected.stats.to_dict()},
        'limitations':['Only one financial configuration migrated; complete candidate universe and all stage-four checks remain pending.',
            'Daily-close timestamps are explicit; old intrabar TIMESTAMP labels are replaced with V4 MODEL_BAR_OPEN/BAR_INTERVAL, not exact observed fill timestamps.',
            'No production, frozen package or historical evidence modified.']}
    (HOME/'others/comparison.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    (HOME/'others/window_reader_probe.json').write_text(json.dumps(projected.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':output['status'],'accounts':[{k:r[k] for k in ('scenario','max_fill_differences','max_daily_account_differences','max_benchmark_equity_difference','old','new')} for r in result],
        'reader':output['current_selection_reader']},ensure_ascii=False))

if __name__=='__main__': main()
