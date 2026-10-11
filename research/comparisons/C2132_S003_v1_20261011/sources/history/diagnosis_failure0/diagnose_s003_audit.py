"""Read-only public ReplayEvidence audit of the single authorized S003 center."""
from hashlib import sha256
from pathlib import Path
import json

from czsc_trader.research_tools import EvidenceRef
from strategy_evaluator import ReplayEvidence, audit_replay, hash_replay_evidence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
receipts_path = ROOT / 'research/comparisons/C2132_S003_v1_20261011/account_receipts.json'
receipts_raw = receipts_path.read_bytes()
receipts = json.loads(receipts_raw)
selected = [item for item in receipts if item['family'] == 'S003']
assert len(selected) == 1
reference = EvidenceRef.from_dict(selected[0]['center'])
assert reference.experiment.strategy_id == 'S003'
source = reference.resolve(ROOT)
raw = source.read_bytes()
assert sha256(raw).hexdigest() == reference.sha256
value = json.loads(raw)
assert len(value['runs']) == 1
run = value['runs'][0]
replay = ReplayEvidence.from_dict(run['replay_evidence'])
audit = audit_replay(replay)
assert hash_replay_evidence(replay) == replay.content_hash
result = {
    'status': 'READONLY_PUBLIC_AUDIT_DIAGNOSIS',
    'reference': reference.to_dict(), 'published_bytes_sha256': reference.sha256,
    'receipts_sha256': sha256(receipts_raw).hexdigest(),
    'request_hash': value['request_hash'], 'result_hash': value['result_hash'],
    'window_id': run['window_id'], 'scenario_id': run['scenario_id'],
    'request_execution_mode': value['execution_mode'],
    'replay_execution_spec': dict(replay.execution_spec),
    'public_audit': audit.to_dict(),
    'counts': {key: len(getattr(replay, key)) for key in
               ['evaluation_sessions', 'decisions', 'orders', 'fills', 'account_daily',
                'trades', 'execution_daily', 'execution_intraday']},
    'schema_fields': {key: sorted(getattr(replay, key)[0]) if getattr(replay, key) else []
                      for key in ['decisions', 'orders', 'fills', 'account_daily', 'trades']},
    'public_source_sha256': sha256((ROOT / 'packages/strategy_evaluator/src/strategy_evaluator/replay_audit.py').read_bytes()).hexdigest(),
    'diagnostic_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
    'account_evaluations': 0, 'account_preparations': 0, 'market_reads': 0,
    'account_sources_read': 1, 'financial_source_changes': 0, 'platform_changes': 0,
}
(HERE / 's003_audit_diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'public_audit': result['public_audit'], 'execution_mode': value['execution_mode'],
                  'execution_spec': dict(replay.execution_spec), 'counts': result['counts'],
                  'schema_fields': result['schema_fields']}, ensure_ascii=False, indent=2))
