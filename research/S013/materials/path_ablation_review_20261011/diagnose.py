"""Read-only summaries of already published EX012 paths; no strategy replay."""
import json
from pathlib import Path
from collections import Counter, defaultdict
from statistics import mean
from hashlib import sha256

root = next(p for p in Path(__file__).resolve().parents if (p / 'research/S013').is_dir())
source = root / 'research/S013/assets/runs/EX012_20261011/analysis_r1.json'
data = json.loads(source.read_text(encoding='utf-8'))
assert data['status'] == 'PASS', data['status']
rows = {r['background'] + '-' + r['mode']: r for r in data['rows']}
out = {'source': source.relative_to(root).as_posix(), 'source_sha256': sha256(source.read_bytes()).hexdigest(),
       'scope': 'Existing completed accounts only. Cycle returns are descriptive, not additive full-policy attribution.',
       'groups': {}, 'entry_pairs': {}}
for label in ('B0-M1', 'B1-M1', 'B2-M1'):
    groups = defaultdict(list)
    for c in rows[label]['paths']['cycles']:
        if c['status'] == 'CLOSED':
            groups[(c['entry_route'], c['exit_reason'])].append(c)
    out['groups'][label] = [dict(route=k[0], exit_reason=k[1], n=len(v),
        mean_net_cycle_return=mean(c['net_return'] for c in v),
        negative_cycles=sum(c['net_return'] < 0 for c in v),
        mean_holding_sessions=mean(c['holding_sessions'] for c in v)) for k, v in groups.items()]
    out['groups'][label].append({'year2023_closed': [{k: c[k] for k in
        ('entry_signal_date','entry_route','entry_acf','entry_range_position','exit_signal_date','exit_reason','net_return','holding_sessions')}
        for c in rows[label]['paths']['cycles'] if c['status']=='CLOSED' and c['entry_fill_year']==2023]})
base = {(c['entry_fill_time'],c['entry_route']): c for c in rows['B0-M1']['paths']['cycles'] if c['status']=='CLOSED'}
for label in ('B1-M1','B2-M1'):
    new = {(c['entry_fill_time'],c['entry_route']): c for c in rows[label]['paths']['cycles'] if c['status']=='CLOSED'}
    keys = base.keys() & new.keys()
    changed = [k for k in keys if base[k]['exit_fill_time'] != new[k]['exit_fill_time']]
    extra = [c for k,c in new.items() if k not in base]
    missing = [c for k,c in base.items() if k not in new]
    out['entry_pairs'][label] = {'same_entry_route':len(keys),'changed_exit':len(changed),
        'different_or_added_entries':len(extra),'different_or_removed_entries':len(missing),
        'extra_routes':dict(Counter(c['entry_route'] for c in extra)),
        'direct_band_extra_bear_cycles':[ {k:c[k] for k in ('entry_signal_date','entry_acf','entry_range_position','exit_reason','net_return')}
            for c in extra if c['entry_route']=='bear' and .045 <= c['entry_acf'] < .1],
        'changed_exit_cycles':[{'entry_fill_time':k[0],'route':k[1],
            'original_exit':base[k]['exit_fill_time'],'new_exit':new[k]['exit_fill_time'],
            'original_reason':base[k]['exit_reason'],'new_reason':new[k]['exit_reason'],
            'original_net_return':base[k]['net_return'],'new_net_return':new[k]['net_return'],
            'cycle_return_difference':new[k]['net_return']-base[k]['net_return']} for k in sorted(changed)]}
dest = Path(__file__).resolve().with_name('diagnostic.json')
dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k not in ('groups','entry_pairs')},ensure_ascii=False))
for label, groups in out['groups'].items():
    print(label, json.dumps([g for g in groups if 'route' in g],ensure_ascii=False))
for label,pairs in out['entry_pairs'].items():
    print(label,json.dumps({k:v for k,v in pairs.items() if not isinstance(v,list)},ensure_ascii=False))
    for c in pairs['direct_band_extra_bear_cycles']:
        print('BAND',json.dumps(c,ensure_ascii=False))
    for c in pairs['changed_exit_cycles']:
        print('EXIT',json.dumps(c,ensure_ascii=False))
