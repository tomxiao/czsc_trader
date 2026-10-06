"""Read-only counts of original screening parameters and serialized behavior."""
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

root = Path.cwd()
task = root / '.tmp/s012-stage3-native-20261006'
parameters, behavior, policies, planned = set(), set(), set(), set()
counts = Counter()
evidence = []
for eid in ('EX049_20261006', 'EX051_20261006'):
    rex = root / 'experiments/S012' / eid / 'artifacts/rex'
    path = rex / 'search.json'
    search = json.loads(path.read_text(encoding='utf-8'))
    evidence.append({'path': path.relative_to(root).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()})
    for row in search['proposals']:
        counts[row['status']] += 1
        scope = {key: value for key, value in row['scope'].items() if key != 'gate_sha256'}
        parameters.add(json.dumps([row['parameters'], scope], sort_keys=True, separators=(',', ':')))
        behavior.add(row['behavior_sha256'])
        policies.add(row['signal_policy_sha256'])
        item = row['raw_ledgers']['signals']
        payload = (rex / item['path']).read_bytes()
        assert sha256(payload).hexdigest() == item['sha256']
        raw = gzip.decompress(payload)
        assert sha256(raw).hexdigest() == item['uncompressed_sha256']
        table = json.loads(raw)
        # Actual pandas table serialization: keep dates and planned position/age/cycle.
        fields = ('dt', 'planned_target', 'planned_age', 'planned_cycle_id')
        value = [[values[name] for name in fields] for values in table['data']]
        planned.add(sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest())
summary = {'status': 'PASS', 'submitted': sum(counts.values()), 'status_counts': dict(counts),
    'unique_parameter_and_scope_except_gate': len(parameters), 'duplicate_submissions': sum(counts.values()) - len(parameters),
    'unique_serialized_trade_behavior': len(behavior), 'unique_signal_and_execution_policy': len(policies),
    'unique_planned_position_age_cycle_sequences': len(planned), 'evidence': evidence,
    'interpretation': 'Parameter/policy, actual transaction behavior, and planned schedules differ. None is a count of independent return mechanisms.',
    'new_accounts_or_fetch': False}
target = task / 'current_search_behavior_counts.json'
with target.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(summary, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps(summary, ensure_ascii=False))
