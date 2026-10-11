"""Formal EX079 delivery and exact per-experiment report copy."""
from hashlib import sha256
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_net_research as driver

WORK = driver.OUT
plan = driver.read(WORK / 'plan.json')
exp = ExperimentRef.from_dict(plan['experiment'])
protocols = exp.resolve(ROOT) / 'protocols'
refs = {**driver.read(protocols / 'method_references.json'), **driver.read(protocols / 'result_references.json'), **driver.read(protocols / 'audit_references.json')}
review = driver.read(WORK / 'root_review.json')
if review['status'] != 'ROOT_REVIEWED' or review['objective_achieved'] or review['original_four_hard_gates_changed'] or review['new_accounts']:
    raise ValueError('Unchanged gates and reviewed component-only outcome required')
for name in ('plan.json', 'statistics.json', 'verification.json'):
    if review['evidence_references'][name] != refs[name]:
        raise ValueError('Review binding differs')
for ref in refs.values():
    driver.public(ref)
if driver.read(driver.public(refs['verification.json']))['status'] != 'PASS':
    raise ValueError('Independent audit must pass')
predecessors = tuple(d.DeliveryReference.from_dict(x) for x in plan['predecessors'])
if len(predecessors) != 1 or predecessors[0].revision != 6 or predecessors[0].stage != d.DeliveryStage.MANDATE:
    raise ValueError('Original MANDATE6 required')
ctx = driver.common.context(1)
for name, path in {'root_review.json': WORK / 'root_review.json', 'closeout.py': Path(__file__), 'root_review.py': ROOT / '.tmp/s013_net_review.py'}.items():
    refs[name] = driver.put(ctx, exp, path)
    if path.suffix == '.py':
        (exp.resolve(ROOT) / 'src' / name).write_bytes(path.read_bytes())
budget = {'status': 'ROUND1_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT', 'authorization_reference': plan['continuation_budget_reference'], 'maximum_additional_experiments': 10, 'started': 1, 'completed': 1, 'completed_experiment': exp.to_dict(), 'remaining': 9, 'next_allowed': 'EX080', 'last_allowed': 'EX088', 'pause_after_EX088': True, 'objective_achieved': False}
driver.write(WORK / 'budget_receipt.json', budget)
refs['budget_receipt.json'] = driver.put(ctx, exp, WORK / 'budget_receipt.json')
tests = tuple(d.ComponentTestResult('NET-OPPORTUNITY-' + model.upper(), exp.experiment_id, EvidenceRef.from_dict(refs['plan.json']), d.ComponentTestStatus(role['status']), role['judgment'], tuple(EvidenceRef.from_dict(refs[name]) for name in ('statistics.json', 'verification.json', 'root_review.json'))) for model, role in review['roles'].items())
entry = d.ComponentEntry(
    'ORIGINAL-INFORMATION-NET-OPPORTUNITY-H4',
    d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-base-net-opportunity/inputs.py']), 'construct'),
    '过去均值、原确认分数与原14信息联合的事前正净机会识别，固定三表达与盈亏阈值0',
    '下一OPEN到第5个未来OPEN，乘.999/1.001-1，扣两侧费用小数份价格代理，非原限价真实账本',
    '固定四个完整session，原全T五相位；无期限扫描',
    '成熟年度训练ECDF/ridge10，旧1388mean/joint预测精确复用，新确认六年拟合，500x40共享块8项CI',
    'T完成已知原14特征；测试预测不用未来标签；辅助原confirmation_opportunity含anchor政策前缀，仅描述不训练',
    '原510500.SH开发池2020-01-02..2026-09-30/HFQ/1m/lot100/.001/原1%执行合同保持；0新账户',
    '同一已见开发池，伪样本外非封存；重叠标签、薄分组、忽略限价/整手/非重叠资金/真实退出；全部区间跨零，不证明原四门与32点达标',
    review['judgment'], tests,
)
report = review['report_markdown'] + '\n\n正式证据（项目根目录相对路径）：\n\n' + ''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name, ref in refs.items())
evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(value) for value in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference'])))
receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(d.ResearchBatchRef('S013'), d.DeliveryStage.COMPONENTS, 14, predecessors), d.DeliveryContent(d.ComponentPanel((entry,), review['judgment']), d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=evidence))
driver.write(protocols / 'delivery_reference.json', receipt.reference.to_dict())
validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
driver.write(protocols / 'delivery_validation.json', validation.to_dict())
driver.write(protocols / 'closeout_references.json', refs)
if validation.status.value != 'PASS':
    raise RuntimeError(validation.to_dict())
formal = ROOT / 'research/S013/deliveries/COMPONENTS/14/report.md'
target = exp.resolve(ROOT) / 'others/report.md'
target.parent.mkdir(exist_ok=True)
with target.open('xb') as stream:
    stream.write(formal.read_bytes())
if target.read_bytes() != formal.read_bytes():
    raise ValueError('Formal and experiment report differ')
copy_proof = {'status': 'PASS', 'formal_report': formal.relative_to(ROOT).as_posix(), 'experiment_report': target.relative_to(ROOT).as_posix(), 'formal_sha256': sha256(formal.read_bytes()).hexdigest(), 'copy_sha256': sha256(target.read_bytes()).hexdigest(), 'exact_bytes': True, 'human_instruction': plan['report_copy']['human_authorization']}
driver.write(protocols / 'report_copy_verification.json', copy_proof)
print({'experiment': exp.experiment_id, 'COMPONENTS': 14, 'FULL': 'PASS', 'report_copy': 'PASS', 'quota_completed': 1, 'remaining': 9}, flush=True)
