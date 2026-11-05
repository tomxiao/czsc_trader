"""Record final S002 equivalence interpretation; immutable evidence stays unchanged."""
from pathlib import Path
import json
import shutil
import sys
import pandas as pd

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from research.S002.runtime_upgrade_v4.build import build_candidate
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, MaterialEvidenceWrite

out = ROOT / '.tmp/rsch-frozen-v4-upgrade/S001_S002'
read = lambda name: json.loads((out / name).read_text(encoding='utf-8'))
comparison = read('S002-final-account-comparison.json')
account = read('S002-final-account.json')['runs']['candidate']
oldroot = ROOT / 'research/S002/experiments/EX002_20261026/others/S002-v1/published_equivalence'
old = pd.read_csv(oldroot / 'old_CONTINUOUS_orders.csv')
orders = account['orders']
assert len(old) == len(orders) == 3
for row, new in zip(old.to_dict('records'), orders):
    assert row['execution_date'] == pd.Timestamp(new['valid_start']).tz_convert('Asia/Shanghai').date().isoformat()
    assert all(row[key] == new[key] for key in ('side', 'quantity', 'order_type'))
    if row['order_type'] == 'LIMIT':
        assert row['limit_price'] == new['limit_price']
    assert {'UNFILLED': 'EXPIRED', 'FILLED': 'FILLED'}[row['status']] == new['status']
days = pd.read_csv(oldroot / 'old_CONTINUOUS_account_daily.csv')
assert days.loc[days.date >= '2026-07-22', 'date'].tolist() == [row['session'] for row in account['account_daily']]
comparison['orders'] = {
    'rows': 3, 'execution_dates_side_quantity_type_limit_buy': 'EXACT',
    'status_mapping': {'UNFILLED': 'EXPIRED', 'FILLED': 'FILLED'},
    'market_sell_limit': 'Legacy stored reference 8.037 is informational; native MARKET has no limit, same market-open fill 7.993',
    'unfilled_order': '2026-08-04 BUY 13400 LIMIT 7.42; not crossed in both accounts'}
(out / 'S002-final-account-comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
candidate = build_candidate()
assert candidate.content_identity.content_sha256 == comparison['content_sha256']
experiment = ExperimentRef.from_dict(comparison['experiment'])
context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S002'),
                                  execution_spec=candidate.definition.execution_spec)
references = {}
for name, path in [('equivalence-comparison', out/'S002-final-account-comparison.json'),
                   ('verified-no-action-source', out/'S002-no-action-source.json')]:
    reference = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(),
                                                               'application/json', 'json'))
    references[name] = reference.to_dict()
(out/'S002-final-material-refs.json').write_text(json.dumps(references, ensure_ascii=False, indent=2), encoding='utf-8')
home = experiment.resolve(ROOT)
for name in ('run_s002_account.py', 'inspect_s002.py', 'close_s002.py'):
    shutil.copyfile(ROOT/'.tmp/rsch-frozen-v4-upgrade'/name, home/'src'/name)
for name in ('S002-final-account-comparison.json', 'S002-final-inspection.json',
             'S002-final-registration.json', 'S002-inspection-first-fixture-failure.json', 'S002-inspection-second-fixture-failure.json'):
    shutil.copyfile(out/name, home/'others'/name)
print(json.dumps({'experiment': experiment.to_dict(), 'references': references}, ensure_ascii=False))
