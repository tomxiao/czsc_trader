"""Compare only immutable saved account and signal observations."""
import json
from hashlib import sha256
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity


def compare_saved(root,item):
    oldref=EvidenceRef.from_dict(item['old_reference'])
    content=oldref.resolve(root).read_bytes()
    assert sha256(content).hexdigest()==oldref.sha256
    oldrun=next(r for r in json.loads(content)['runs'] if r['window_id']==item['window'])
    old=oldrun['replay_evidence']
    newref=EvidenceRef.from_dict(item['reference']); path=newref.resolve(root)
    content=path.read_bytes(); assert sha256(content).hexdigest()==newref.sha256
    full=materialize_equity(content,lambda r:(path.parent/(r['sha256']+'.json')).read_bytes()).payload
    new=full['runs']['candidate']
    mismatches=[]
    def condition(ok,label):
        if not ok: mismatches.append(label)
    signals=oldrun['signals']['data']
    condition(len(signals)==len(new['decisions']),'signal_count')
    for i,(a,b) in enumerate(zip(signals,new['decisions'])):
        day=pd.Timestamp(b['observed_through']).tz_convert('Asia/Shanghai').date().isoformat()
        condition(a['signal_date'][:10]==day and float(a['target_position'])==b['target'],f'signal_{i}')
    condition(len(old['fills'])==len(new['fills']),'fill_count')
    numeric={k:0. for k in ('price','quantity','fees')}
    for i,(a,b) in enumerate(zip(old['fills'],new['fills'])):
        condition(a['side']==b['side'],f'fill_side_{i}')
        condition(a['fill_time'][:10]==pd.Timestamp(b['interval_start']).tz_convert('Asia/Shanghai').date().isoformat(),f'fill_date_{i}')
        for k in numeric:numeric[k]=max(numeric[k],abs(a[k]-b[k]))
    condition(len(old['account_daily'])==len(new['account_daily']),'account_count')
    accounts={k:0. for k in ('cash','quantity','close','equity')}
    for i,(a,b) in enumerate(zip(old['account_daily'],new['account_daily'])):
        condition(a['date'][:10]==b['session'],f'account_date_{i}')
        for k in accounts: accounts[k]=max(accounts[k],abs(a[k]-b[k]))
    ob=oldrun['buyhold']['account_daily']['data'];nb=full['runs']['buy_hold']['account_daily']
    condition(len(ob)==len(nb),'benchmark_count')
    benchmark=max(abs(a['equity']-b['equity']) for a,b in zip(ob,nb))
    condition(max(numeric.values())<=1e-8,'fill_numeric_tolerance')
    condition(max(accounts.values())<=1e-8,'account_numeric_tolerance')
    condition(benchmark<=1e-8,'benchmark_numeric_tolerance')
    return {'status':'PASS' if not mismatches else 'FAIL','absolute_tolerance':1e-8,'mismatches':mismatches,
        'signal_count':len(signals),'new_signal_count':len(new['decisions']),
        'fills':len(old['fills']),'new_fills':len(new['fills']),
        'max_fill_differences':numeric,'max_daily_account_differences':accounts,
        'max_benchmark_equity_difference':benchmark,'new_metrics':new['metrics'],
        'old_metrics':old['metrics'],'old_reference':item['old_reference'],'new_reference':item['reference']}
