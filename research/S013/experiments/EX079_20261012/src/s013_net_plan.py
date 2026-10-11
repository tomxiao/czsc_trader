"""Bind the fixed source-only method and authorized first budget slot."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-base-net-opportunity'


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


freeze = read(WORK / 'source_freeze.json')
for name, expected in freeze['files'].items():
    if digest(WORK / name) != expected:
        raise ValueError('Source freeze drift')
for name, expected in freeze['numeric_dependencies'].items():
    if digest(ROOT / name) != expected:
        raise ValueError('Numeric dependency drift')
if read(WORK / 'focused_checks.json')['status'] != 'PASS':
    raise ValueError('Focused synthetic pass required')
ex78 = ROOT / 'research/S013/experiments/EX078_20261012/protocols'
if read(ex78 / 'delivery_validation.json')['status'] != 'PASS':
    raise ValueError('EX078 FULL closeout required beforeEX079')
refs66 = read(ROOT / 'research/S013/experiments/EX066_20261011/protocols/result_references.json')
p71 = read(ROOT / 'research/S013/experiments/EX071_20261011/protocols/plan.json')
p78 = read(ex78 / 'plan.json')
sources = sorted(WORK.glob('*.py')) + [ROOT / '.tmp/s013_net_research.py', ROOT / '.tmp/s013_net_plan.py', ROOT / 'research/S013/experiments/EX058_20261011/src/common.py', ROOT / 'research/S013/experiments/EX066_20261011/src/opportunity_statistics.py']
audit_dir = ROOT / '.tmp/s013-base-net-audit'
audit_freeze = read(audit_dir / 'freeze.json')
for name, expected in audit_freeze['files'].items():
    if digest(audit_dir / name) != expected:
        raise ValueError('Independent source freeze drift')
plan = {
    'status': 'PROSPECTIVE_DECLARED', 'role': 'RSCH', 'stage': 2,
    'frozen_utc': datetime.now(timezone.utc).isoformat(),
    'authorization': '用户授权自主研究；EX078完成后追加10轮；每个后续实验保存report副本',
    'objective': '原四门不变，寻找扣费后机会识别依据，最终改善标准32点CAGR_Q10/DD_Q90；本轮仅价格机会诊断',
    'original_four_hard_gates_changed': False, 'new_hard_gates': False,
    'quota_slot': 1, 'maximum_additional_experiments': 10, 'pause_after_EX088': True,
    'continuation_budget_reference': read(ex78 / 'continuation_budget_reference.json'),
    'scientific_definition': read(WORK / 'prospective_plan.json'),
    'method': read(WORK / 'method.json'),
    'selection_history': '同一已见开发池，EX066同口径14项联合/均值预测复用1388条，不称新发现；EX078固定退出组件无支持。本轮新确认单分数模型及正预测机会组/共享区间，未校正反复研究选择。',
    'input_references': {**{name: refs66[name] for name in ('features.csv', 'labels.csv', 'opportunity.csv', 'prices.csv', 'statistics.json', 'input_checks.json')}, 'native': p71['native_ref']},
    'source_files': {p.relative_to(ROOT).as_posix(): digest(p) for p in sources},
    'audit_source_files': {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(audit_dir.iterdir()) if p.suffix in ('.json', '.py')},
    'auxiliary_origin': 'EX066 opportunity.csv is entry_eligible; check against native same metadata, but derive planned policy-flat auxiliary from authenticated complete C8880 decisions.confirmation_opportunity including2019anchor prefix, never rename old eligibility as flat opportunity',
    'native_cache': {'.tmp/s013-mechanism-EX058/N0.pkl.gz': 'ceded25c20adb4e698ec4dfecd677d26db62c342f339d83be3c0b592a451d26c'},
    'predecessors': p78['predecessors'],
    'resources': {'workers': 1, 'blas_threads': 1, 'new_confirmation_year_fits': 6, 'reused_mean_joint_models': True, 'statistics_calls': 1, 'new_accounts': 0, 'provider_calls': 0},
    'report_copy': {'target': 'others/report.md', 'source': 'corresponding formal delivery report.md', 'verification': 'exact bytes andSHA256', 'human_authorization': 'RSCH，请在后续的每个实验目录下保存一份report副本'},
    'stopping': '固定h4/alpha10/阈值0/三表达/8区间，未得到可识别净机会依据则不自动追加账户；不改窗口、翻符号或挑年份救援',
}
with (WORK / 'prospective.json').open('x', encoding='utf-8') as stream:
    json.dump(plan, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.write('\n')
print({'status': 'FROZEN', 'quota_slot': 1, 'source_n': len(sources), 'new_accounts': 0})
