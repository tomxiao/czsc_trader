"""Describe existing longer bear cycles; never replay or value a new policy."""
from pathlib import Path
from hashlib import sha256
from statistics import mean
from collections import Counter
import sys
import json
import pandas as pd

root=next(p for p in Path(__file__).resolve().parents if (p/'research/S013').is_dir())
sys.path.insert(0,str(root/'research/S013/experiments/EX013_20261011/src'))
from common import cache_read,context

source=root/'research/S013/assets/runs/EX013_20261011/analysis.json'
analysis=json.loads(source.read_text(encoding='utf-8'))
refs=json.loads((root/'research/S013/assets/runs/EX013_20261011/account_references.json').read_text(encoding='utf-8'))
assert analysis['status']=='PASS'
output={'source':source.relative_to(root).as_posix(),'source_sha256':sha256(source.read_bytes()).hexdigest(),
    'scope':'Descriptive observations of completed EX013/EX012 accounts only. Future exits and cycle returns are labels; decision predicates use contemporaneous closes. No new strategy account or policy attribution.',
    'backgrounds':{}}
ctx=context(1)
for original_label,long_label in [('B0-M1','N1'),('B1-M1','N3')]:
    original=analysis['rows'][original_label]
    long=analysis['rows'][long_label]
    bound,result=cache_read(root/'.tmp/s013-mechanism-EX013'/(long_label+'.pkl.gz'))
    ref=refs[long_label]
    formal=root/'research/S013/assets/evidence/EX013_20261011'/ref['evidence_id']
    raw=formal.read_bytes()
    assert sha256(raw).hexdigest()==ref['sha256']
    recorded=json.loads(raw)
    assert recorded['request_hash']==result.request_hash and recorded['result_hash']==result.result_hash
    assert recorded['request_identity']['content_sha256']==long['content_sha256']
    frame=result.runs[0].signals.decisions.copy()
    frame['normalized_date']=frame.signal_date.astype('datetime64[ns]').dt.normalize()
    assert frame.normalized_date.is_unique
    binding=next(iter(bound.input_bindings.values()))
    fetched=ctx.data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert fetched.ready,fetched.error
    bars=fetched.dataframe
    close=dict(zip(pd.to_datetime(bars.Date).dt.strftime('%Y-%m-%d'),bars.Close,strict=True))
    dates=list(frame.normalized_date.dt.strftime('%Y-%m-%d'))
    assert all(day in close for day in dates)
    original_cycles=[c for c in original['paths']['cycles'] if c['status']=='CLOSED']
    long_cycles=[c for c in long['paths']['cycles'] if c['status']=='CLOSED']
    original_map={(c['entry_fill_time'],c['entry_route']):c for c in original_cycles}
    extended=[]
    paired=[]
    for cycle in long_cycles:
        if cycle['entry_route']!='bear':
            continue
        entry=cycle['entry_signal_date'][:10]
        exit_date=cycle['exit_signal_date'][:10]
        entry_index=dates.index(entry)
        deadline_index=entry_index+4
        if deadline_index>=len(dates) or dates[deadline_index]>=exit_date:
            continue
        day=dates[deadline_index]
        previous=dates[deadline_index-1]
        delta=close[day]-close[previous]
        direction='up' if delta>0 else 'down' if delta<0 else 'equal'
        mark_vs_signal=close[day]/close[entry]-1
        row={k:cycle[k] for k in ('entry_signal_date','exit_signal_date','exit_reason','holding_sessions','net_return')}
        row.update(deadline_signal_date=day,deadline_close_direction=direction,
            deadline_close_vs_entry_signal_close=mark_vs_signal)
        extended.append(row)
        key=(cycle['entry_fill_time'],cycle['entry_route'])
        if key in original_map and original_map[key]['exit_reason']=='time':
            predecessor=original_map[key]
            assert predecessor['exit_signal_date'][:10]==day
            paired.append({**row,'original_net_return':predecessor['net_return'],
                'cycle_return_difference':cycle['net_return']-predecessor['net_return']})
    def summarize(records,key):
        return {value:{'n':len(group),'positive_final_cycles':sum(r['net_return']>0 for r in group),
            'mean_final_cycle_return':mean(r['net_return'] for r in group)}
            for value in sorted({r[key] for r in records}) if (group:=[r for r in records if r[key]==value])}
    output['backgrounds'][original_label]={'no_timer_label':long_label,
        'source_account_reference':ref,
        'prepared_reference':binding.to_dict()['prepared'],
        'daily_request':binding.to_dict()['plan']['requests']['daily'],
        'input_binding_sha256':sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'closed_bear_cycles':sum(c['entry_route']=='bear' for c in long_cycles),
        'extended_beyond_day4':len(extended),'deadline_directions':dict(Counter(r['deadline_close_direction'] for r in extended)),
        'below_entry_signal_close_at_day4':sum(r['deadline_close_vs_entry_signal_close']<0 for r in extended),
        'extended_group_description':summarize(extended,'deadline_close_direction'),
        'same_entry_original_time_exit_pairs':len(paired),
        'paired_groups':{direction:{'n':len(group),'improved_cycles':sum(r['cycle_return_difference']>0 for r in group),
            'worsened_cycles':sum(r['cycle_return_difference']<0 for r in group),
            'mean_cycle_return_difference':mean(r['cycle_return_difference'] for r in group)}
            for direction in ('up','down','equal') if (group:=[r for r in paired if r['deadline_close_direction']==direction])},
        'extended_cycles':extended,'same_entry_pairs':paired}
folder=root/'research/S013/materials/conditional_exit_review_20261011'
(folder/'diagnostic.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({key:{k:v for k,v in group.items() if k not in ('extended_cycles','same_entry_pairs','source_account_reference','prepared_reference','daily_request','input_binding_sha256')} for key,group in output['backgrounds'].items()},ensure_ascii=False))
