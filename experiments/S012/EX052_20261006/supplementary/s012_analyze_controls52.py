"""Interpret serialized causal state and controls; no new market computation."""
from hashlib import sha256
import gzip
import json
from pathlib import Path

root = Path.cwd()
task = root / '.tmp/s012-stage3-native-20261006'
read = lambda path: json.loads(path.read_text(encoding='utf-8'))
def ref(path):
    return {'path': path.relative_to(root).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}
def full(eid, cid):
    rex = root / 'experiments/S012' / eid / 'artifacts/rex'
    row = next(row for row in read(rex / 'trials.json') if row['candidate_id'] == cid)
    item = row['record']['result_artifact']
    path = rex / item['path']
    assert ref(path)['sha256'] == item['sha256']
    run = read(path)['runs'][0]
    return row, run['ledgers']['decisions']['data'], ref(path)
def entries(decisions, datekey):
    prior = 0
    dates = []
    for row in decisions:
        if row['planned_target'] > 0 and prior == 0:
            dates.append(row[datekey])
        prior = row['planned_target']
    return dates

audit = read(task / 'audit_EX052.json')
assert audit['status'] == 'PASS' and not audit['errors']
base, bdec, bref = full('EX050_20261006', 'C4603')
h5, hdec, href = full('EX052_20261006', 'C4700')
assert entries(bdec, 'signal_date') == entries(hdec, 'signal_date')
rex = root / 'experiments/S012/EX051_20261006/artifacts/rex'
search = read(rex / 'search.json')
params = dict(base['parameters'], hold_days=8)
screen = next(row for row in search['proposals'] if row['parameters'] == params)
item = screen['raw_ledgers']['signals']
path = rex / item['path']
assert ref(path)['sha256'] == item['sha256']
raw = gzip.decompress(path.read_bytes())
assert sha256(raw).hexdigest() == item['uncompressed_sha256']
sdec = json.loads(raw)['data']
h6c2, cdec, cref = full('EX052_20261006', 'C4701')
assert entries(sdec, 'dt') == entries(cdec, 'signal_date')
mom, _, mref = full('EX050_20261006', 'C4605')
known, kdec, kref = full('EX052_20261006', 'C4703')
joint, _, jref = full('EX052_20261006', 'C4704')
trail, _, tref = full('EX050_20261006', 'C4607')
value = {'status': 'PASS', 'new_accounts': 0, 'new_fetches': 0,
    'same_planned_entry_tests': [
        {'control': 'C4700 h5/c1', 'base': 'C4603 h6/c0', 'same_signal_entry_dates': True,
            'planned_entries': len(entries(bdec, 'signal_date')), 'control_cagr': h5['metrics']['net_cagr'],
            'base_cagr': base['metrics']['net_cagr'], 'difference_percentage_points': 100*(h5['metrics']['net_cagr']-base['metrics']['net_cagr']),
            'evidence': [bref, href]},
        {'control': 'C4701 h6/c2', 'base': 'EX051 '+screen['proposal_id']+' h8/c0', 'same_signal_entry_dates': True,
            'planned_entries': len(entries(cdec, 'signal_date')), 'control_cagr': h6c2['metrics']['net_cagr'],
            'base_cagr': screen['metrics']['net_cagr'], 'difference_percentage_points': 100*(h6c2['metrics']['net_cagr']-screen['metrics']['net_cagr']),
            'base_mode': 'ORIGINAL_SCOPED_SCREENING_NOT_FULL', 'evidence': [ref(path), cref]}],
    'unknown_policy': {'base': 'C4605 BLOCK', 'control': 'C4703 KNOWN_ONLY',
        'base_cagr': mom['metrics']['net_cagr'], 'control_cagr': known['metrics']['net_cagr'],
        'difference_percentage_points': 100*(known['metrics']['net_cagr']-mom['metrics']['net_cagr']),
        'closed_before': mom['metrics']['closed_trades'], 'closed_after': known['metrics']['closed_trades'],
        'interpretation': '385 unknown sessions in 2020/21 regain participation. Account and planned state propagate continuously later; no stronger forecasting claim or cash reset.',
        'evidence': [mref, kref]},
    'joint_control': {'candidate_id': 'C4704', 'cagr': joint['metrics']['net_cagr'],
        'vs_premium020_percentage_points': 100*(joint['metrics']['net_cagr']-base['metrics']['net_cagr']),
        'vs_trail050_percentage_points': 100*(joint['metrics']['net_cagr']-trail['metrics']['net_cagr']),
        'remaining_cagr_gap_percentage_points': 100*(joint['metrics']['benchmark']['cagr']*1.5-joint['metrics']['net_cagr']),
        'evidence': [jref, bref, tref]},
    'evidence': [ref(task / 'audit_EX052.json'), ref(task / 'delivery-prep/EX052_20261006_full_diagnosis.json')]}
target = task / 'controls52_interpretation.json'
with target.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.write('\n')
print(json.dumps(value, ensure_ascii=False))
