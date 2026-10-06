"""Root readback of the exact risk-exit pair, then seal only a nonqualified result."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from research_experiment import experiment_source_sha256, load_experiment_input

root = Path.cwd()
task = root / '.tmp/s012-stage3-native-20261006'
exp = root / 'experiments/S012/EX054_20261006'
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
ref = lambda p: {'path': p.relative_to(root).as_posix(), 'sha256': sha256(p.read_bytes()).hexdigest()}
binding = read(exp / 'experiment_binding.json')
receipt = read(exp / 'artifacts/rex/execution_receipt.json')
assert binding['source_sha256'] == experiment_source_sha256(exp, tuple(binding['source_files'])) == receipt['source_sha256']
assert binding['source_sha256'] == 'f0633d3e5010371f38b63661c15742767ff0d1be924ee4dd0427667e9d3268c9'
load_experiment_input(exp / 'artifacts/rex', expected_receipt_sha256=receipt['receipt_sha256'])
trials = read(exp / 'artifacts/rex/trials.json')
assert len(trials) == len(receipt['trace']['evaluations']) == 1
trial = trials[0]
assert trial['record']['status'] == 'SUCCEEDED' and trial['candidate_id'] == 'C4900'
baseline_path = root / 'experiments/S012/EX053_20261006/artifacts/rex/trials.json'
baseline = next(r for r in read(baseline_path) if r['candidate_id'] == 'C4801')
assert trial['parameters'] == {**baseline['parameters'], 'risk_exit': True}
assert baseline['parameters']['risk_exit'] is False
audit_path = task / 'audit_EX054.json'
audit = read(audit_path)
assert audit['status'] == 'PASS' and not audit['errors'] and audit['experiments'] == [exp.name]
assert audit['verified_receipt_hashes'][exp.name] == receipt['receipt_sha256']
def run(row, eid):
    p = root / 'experiments/S012' / eid / 'artifacts/rex' / row['record']['result_artifact']['path']
    assert ref(p)['sha256'] == row['record']['result_artifact']['sha256']
    return read(p)['runs'][0], ref(p)
actual, actual_ref = run(trial, exp.name)
prior, prior_ref = run(baseline, 'EX053_20261006')
reasons = Counter(r['decision_reason'] for r in actual['ledgers']['decisions']['data'])
delta = {k: trial['metrics'][k] - baseline['metrics'][k] for k in
         ('net_cagr', 'max_drawdown', 'closed_trades', 'frequency', 'final_equity', 'total_fees', 'exposure')}
comparison = {'status': 'PASS', 'candidate_id': 'C4900', 'baseline_id': 'C4801',
    'only_parameter_delta': {'risk_exit': [False, True]}, 'actual': trial['metrics'],
    'baseline': baseline['metrics'], 'delta': delta, 'decision_reason_counts': dict(reasons),
    'evidence': [ref(baseline_path), actual_ref, prior_ref, ref(audit_path)],
    'interpretation_boundary': 'T signal then T+1 sell; prior 38-session association is not avoidable-loss prediction. Whole development pool already seen.'}
target = task / 'delivery-prep/risk_exit54_comparison.json'
with target.open('x', encoding='utf-8', newline='\n') as f:
    json.dump(comparison, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n')
assert not (exp / 'experiment_manifest.json').exists()
for source, dest in [(audit_path, exp / 'artifacts/independent_account_audit.json'),
    (task / 'delivery-prep/EX054_20261006_full_diagnosis.json', exp / 'artifacts/scientific_diagnosis.json'),
    (target, exp / 'artifacts/risk_exit_pair_comparison.json')]:
    assert not dest.exists(); shutil.copyfile(source, dest)
m = trial['metrics']
report = (task / 'delivery-prep/EX054_20261006_04_conclusion.md').read_text(encoding='utf-8')
report += f'''\n## 精确配对的实际归因\n\n仅risk_exit=False改True，C4801原入场/资金/成本/持有期/未知政策全部保持。
净年化{m['net_cagr']:.6%}，相对原6.916237%变化{delta['net_cagr'] * 100:+.6f}个百分点；
权益变化{delta['final_equity']:+.2f}元，费用变化{delta['total_fees']:+.2f}元，闭合周期变化{delta['closed_trades']:+d}。
决策原因的真实计数为{dict(reasons)}。原高峰度38个无成交持仓日的−18510元仅为关联线索；
本配对使用T时点已知状态、T+1真实执行，不能提前消除已发生的隔夜损失，也不能将原损失直接加回权益。
账户完整度与独立审计PASS分别成立；三门为{m['goals']}，经济目标同时达标为{m['passed_all']}。
配对与连续年度详见artifacts/risk_exit_pair_comparison.json及artifacts/scientific_diagnosis.json。
阶段三最终科学收口及公共交付由后继聚合owner承接，不由本项零达标自动推导。\n'''
(exp / '04_conclusion.md').write_text(report, encoding='utf-8', newline='\n')
supplement = exp / 'supplementary'; supplement.mkdir(exist_ok=False)
for source in [task / 'independent_account_check.py', root / '.tmp/s012_build_full_checkpoint.py', Path(__file__).resolve()]:
    shutil.copyfile(source, supplement / source.name)
assert experiment_source_sha256(exp, tuple(binding['source_files'])) == binding['source_sha256']
if not m['passed_all']:
    manifest = build_experiment_manifest(exp, {'strategy_id': 'S012', 'experiment_id': exp.name,
        'symbol': '518850.SH', 'development_cutoff': '2026-09-30', 'outcome': 'FAIL',
        'economic_outcome': 'NO_QUALIFIED', 'complete_rex': True,
        'receipt_sha256': receipt['receipt_sha256'], 'source_sha256': binding['source_sha256'],
        'successful_full': 1, 'qualified': 0, 'independent_account_audit': 'PASS',
        'risk_exit_pair': 'PASS', 'stage_three_complete': False})
    assert validate_experiment_archive(exp) == manifest
    comparison['archive_file_count'] = len(manifest['files'])
else:
    comparison['archive_status'] = 'UNSEALED_QUALIFIED_WAIT_PUBLIC_REGISTRATION'
print(json.dumps(comparison, ensure_ascii=False))
