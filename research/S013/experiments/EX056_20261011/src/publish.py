"""Retain zero-account center-equivalence counterevidence as local FULL52."""
# ruff: noqa: E402
from pathlib import Path
from hashlib import sha256
import json
import sys

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
sys.path.insert(0, str(ROOT / 'research/S013/experiments/EX055_20261011/src'))
from common import context, read, write, file_hash
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey

EXPERIMENT = ExperimentRef('S013', 'EX056_20261011')
PROTOCOLS = SRC.parent / 'protocols'


def main():
    assert not (PROTOCOLS / 'delivery_reference.json').exists()
    result_ref = EvidenceRef.from_dict(read(PROTOCOLS / 'center_equivalence_reference.json'))
    assert file_hash(result_ref.resolve(ROOT)) == result_ref.sha256
    result = read(result_ref.resolve(ROOT))
    assert result['status'] == 'PASS' and result['core_signal_path_exact'] is True
    assert result['economic_account_evaluations'] == result['new_account_preparations'] == 0
    centers = read(ROOT / 'research/S013/assets/runs/EX055_20261011/analysis.json')
    assert centers['status'] == 'PASS' and not centers['rows']['N0']['qualified']
    accounts = read(ROOT / 'research/S013/assets/runs/EX055_20261011/account_references.json')
    method = read(PROTOCOLS / 'method.json')
    assert method['financial_evaluations_before_declaration'] == 0
    ctx = context(1)
    archives = {}
    for label, folder in (('runtime', 'ex056-dual-recovery-prototype'), ('oracle', 'ex056-dual-recovery-oracle'),
                          ('parameter-helpers', 'ex056-param-prototype'), ('parameter-checks', 'ex056-param-checks'),
                          ('center-equivalence', 'ex056-center-equivalence'), ('center-equivalence-v2', 'ex056-center-equivalence-v2'),
                          ('center-equivalence-v3', 'ex056-center-equivalence-v3')):
        base = ROOT / '.tmp' / folder
        assert base.is_dir()
        archives[label] = {p.relative_to(base).as_posix(): {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
                           for p in base.rglob('*') if p.is_file() and p.suffix in ('.py', '.json')}
    archives['retention'] = 'Pure sources, failed attempts, proofs and only readonly existing-center signal formula comparison; no new account evaluation/registration or parameter finance.'
    write(PROTOCOLS / 'prototypes.json', archives)
    materials = {'prospective-mechanism-method': EvidenceRef.from_dict(read(PROTOCOLS / 'method_reference.json')),
        'center-equivalence-method': EvidenceRef.from_dict(read(PROTOCOLS / 'center_equivalence_method_reference.json')),
        'center-equivalence-v2-method': EvidenceRef.from_dict(read(PROTOCOLS / 'center_equivalence_v2_method_reference.json')),
        'center-equivalence-v3-method': EvidenceRef.from_dict(read(PROTOCOLS / 'center_equivalence_v3_method_reference.json')),
        'center-equivalence-v1-failure': EvidenceRef.from_dict(read(PROTOCOLS / 'center_equivalence_failure_reference.json')),
        'center-equivalence-v2-failure': EvidenceRef.from_dict(read(PROTOCOLS / 'center_equivalence_v2_failure_reference.json')),
        'center-equivalence-result': result_ref,
        'previous-two-account-loss-method': EvidenceRef.from_dict(read(ROOT / 'research/S013/experiments/EX055_20261011/protocols/loss_diagnosis_method_reference.json')),
        'previous-two-account-loss-result': EvidenceRef.from_dict(read(ROOT / 'research/S013/experiments/EX055_20261011/protocols/loss_diagnosis_reference.json'))}
    materials['pure-sources-and-proof-history'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT,
        'pure-sources-and-center-equivalence-history', (PROTOCOLS / 'prototypes.json').read_bytes(), 'application/json', 'json'))
    account_refs = {label: EvidenceRef.from_dict(accounts[label]) for label in ('B0-TIME', 'B0-COUPLED', 'N0')}
    conclusion = {'status': 'COMPLETE', 'objective_achieved': False,
        'decision': 'NO_INCREMENTAL_CENTER_SIGNAL_PATH; do not evaluate a new economic account already proven business-path equivalent to failed C7980.',
        'new_account_preparations': 0, 'economic_account_evaluations': 0, 'new_business_accounts': 0,
        'new_parameter_accounts': 0, 'reused_parameter_accounts': 0, 'registrations': 0,
        'scope': 'Original center only, same full1636 decisions; diagnostic entry_direction_up may differ away from recovery. No new native financial evidence or all32 equivalence claimed.',
        'reason': 'All12 actual BODY-only recovery opportunities already satisfy Close>previousClose, including5 original-score refusals. Full independent signal/state comparison proves new strict conjunction adds no changed center business decision.',
        'economic_reference': account_refs['N0'].to_dict(),
        'negative_year_profitability_gate': False,
        'next_action': 'Keep original4 gates/full13 domains/same32; investigate an independently predeclared mechanism with incremental support information, disclosing exposed-pool selection.'}
    write(PROTOCOLS / 'decision.json', conclusion)
    materials['conclusion'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'center-equivalence-conclusion',
        (PROTOCOLS / 'decision.json').read_bytes(), 'application/json', 'json'))
    lines = ['# EX056 双价格方向条件的中心等价反证', '',
        '本轮只读核验完成；改善参数敏感性的总目标尚未达成。', '',
        '事前提出：在EX055局部日内回升恢复相关资格的例外中，再要求收盘高于昨收，检验向下跳空后的反弹。其他原13数值中心、全部上下文、确认和持仓退出规则保持；原相关合格买点不加门。', '',
        '新的账本反证先于新账户实验出现：EX055的12个实际恢复机会（7次信号入场并成交、5次被原确认评分拒绝）全部已经收盘高于昨收。随后按事前独立方法认证旧完整原生身份、绑定行情和日历，重算新公式并逐日核对全部业务信号、资格、分数、上下文、目标与退出，证明中心路径完全相同。仅用于观察的entry_direction_up字段可以在非恢复日不同，完整保留差异，不能假称所有诊断字段也相同。', '',
        '第一次实际只读核验因退出原因列的可空字符串存储类型与新公式object类型不一致而严格拒绝，失败和原方法完整留存。后继方法只对退出原因、路线、类别三列校验合法字符串与空值并归一存储空值表示，其余列仍精确比较。第二次在输出公共身份对象报告时因错误调用to_dict中止；再次事前声明后继方法，仅按公共dataclass四字段准确序列化。最终核验1636日通过，诊断方向字段103日不同全部保留；没有修改状态、公式、数据或经济规则。', '',
        '因此不运行新金融账户，不登记C8280，不启动原32参数账户。对新规则的中心经济判断引用旧C7980原生结果；没有伪造新native账户，也没有从旧交易盈利相减推算收益。尚未证明32个参数路径相同。', '',
        '## 实际既有账户证据', '',
        '| 策略 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2023收益 | 原四门 |',
        '|---|---|---:|---:|---:|---:|---|']
    for key, title in (('B0-TIME', '原策略'), ('B0-COUPLED', '历史均值+CLOSE门'), ('N0', '旧局部BODY资格恢复')):
        row = centers['rows'][key]
        lines.append(f"| {title} | {row['candidate_id']} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {row['annual']['2023']['return']*100:+.4f}% | {'通过' if row['qualified'] else '未通过'} |")
    lines += ['', '旧恢复规则2023价格收益增加约4,168.46元，费用增加约8,635.70元，全年净收益相对原策略减少约4,467.24元。全7年、1,636天、全部成交及尾仓归因完整保留；这不是把两笔额外交易简单删除后的预测。', '',
        '相关性上升、清除跨上涨路线的上下文和上下文年龄都有实际反例：相关性上升仍有两笔恢复交易亏损，未上升也有大赢交易；原2023两个恢复上下文均未跨上涨路线。不能凭单个标签推断改善。', '',
        '纯runtime272项、独立oracle189项及72项拒绝、原13参数辅助73项检查通过；纯证明及其失败修正保留。它们验证语义，中心只读等价核验验证此路径无增量，均不代表经济改善。反复使用已见S013开发池，无独立市场验证；FULL只检验材料完整性。RSCH阶段三。', '',
        '下一步：保持原四门和原参数域，检验具有增量信息的最小机制；不重复已证明相同且未达标的中心账户。', '',
        '新增金融准备0、账户评价0、参数账户0、登记0；信号公式核算使用既有绑定数据，不回放订单或现金。', '', '## 正式证据引用', '']
    evidence = {}
    for name, ref in {**account_refs, **materials}.items():
        assert file_hash(ref.resolve(ROOT)) == ref.sha256
        evidence[ref.repository_path] = ref
        lines.append(f'- [{name}](../../../assets/deliveries/CANDIDATES/52/{ref.path})')
    report = '\n'.join(lines) + '\n'
    (SRC.parent / 'others').mkdir(exist_ok=True)
    (SRC.parent / 'others/report.md').write_text(report, encoding='utf-8', newline='\n')
    reproduction = {'source': Path(__file__).read_text(encoding='utf-8'), 'sha256': file_hash(Path(__file__)),
        'report_sha256': sha256(report.encode('utf-8')).hexdigest(), 'counts': conclusion}
    raw = (json.dumps(reproduction, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    reproduction_ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'delivery-reproduction', raw, 'application/json', 'json'))
    evidence[reproduction_ref.repository_path] = reproduction_ref
    entries = tuple(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', centers['rows'][label]['candidate_id']), centers['rows'][label]['content_sha256']),
        '既有合格原生中心对照', '本轮无新达标候选；未正式阶段四交接', (d.EvaluationEvidenceRef(account_refs[label]),)) for label in ('B0-TIME', 'B0-COUPLED'))
    summary = d.SearchSummary(method['name'], 'StrictBODY AND strictCLOSE local ACF recovery versus historicalBODY-only recovery',
        'Original4 gates/full13 center and domains/same32/score/context/exits/data/cost unchanged', 0, 0,
        'Prospective pure implementation then readonly authenticated full-center signal equivalence; no financial evaluation needed for known failed identical business path.',
        ('Only original center business-path equivalence, not all32', 'Repeatedly observed S013 development pool', 'No independent market validation'),
        (materials['conclusion'], materials['center-equivalence-result'], materials['previous-two-account-loss-result']))
    payload = d.CandidateSet(entries, (), (summary,), '阴性中心等价结果完整保留；未推进阶段或生产。')
    old_plan = read(ROOT / 'research/S013/experiments/EX055_20261011/protocols/plan.json')
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, 52,
        (d.DeliveryReference.from_dict(old_plan['mandate']), d.DeliveryReference.from_dict(method['previous_delivery']))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=tuple(evidence.values())))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value == 'PASS', validation.to_dict()
    write(PROTOCOLS / 'delivery_reference.json', receipt.reference.to_dict())
    write(PROTOCOLS / 'delivery_validation.json', {'status': 'PASS', 'reference': receipt.reference.to_dict(), 'validation': validation.to_dict(), 'counts': conclusion})
    print({'FULL': 'PASS', 'revision': 52, 'reference': receipt.reference.to_dict(), 'new_account_evaluations': 0}, flush=True)


if __name__ == '__main__':
    main()
