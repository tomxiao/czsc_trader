"""Publish EX061 review evidence and immutable COMPONENTS revision 3."""
# ruff: noqa: E402
from pathlib import Path
import json
import shutil
import sys
from czsc_trader.application import assemble_delivery, validate_delivery, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-next-research'
sys.path.insert(0, str(ROOT / 'research/S013/experiments/EX058_20261011/src'))
import common


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    ctx = common.context(1)
    exp = ExperimentRef.from_dict(read(WORK / 'experiment.json'))
    assert exp.experiment_id == 'EX061_20261011'
    path = exp.resolve(ROOT)
    assert not (path / 'protocols/delivery_reference.json').exists()
    refs = read(path / 'protocols/result_references.json')
    verification = read(WORK / 'verification.json')
    judgment = read(WORK / 'judgment.json')
    assert verification['status'] == 'PASS' and verification['check_count'] == 152
    assert judgment['decision']['positive_hypothesis'] == 'STOP_POSITIVE_STRATEGY_TRANSLATION'
    assert not common.SOURCE_CALLS
    conclusion = {
        'status': 'PHASE_TWO_COMPLETE_NO_NEW_STRATEGY',
        'robust_strategy_goal_achieved': False,
        'positive_hypothesis': 'Stop positive tail-recovery strategy translation; retain all strongest positive and negative evidence',
        'reverse_hypothesis': 'Prospective clue only; posthoc EX061 direction not independent confirmation or strategy qualification',
        'new_financial_accounts': 0, 'new_parameter_points': 0, 'candidate_registrations': 0,
        'economic_targets_unchanged': True, 'new_hard_gates': False,
        'sealed_validation_used': False, 'external_data_used': False, 'platform_or_production_changes': False,
        'actual_verification_checks': 152,
        'next_step': 'Predeclare a finite reverse-mechanism comparison against same-row daily BODY/close_location before any executable strategy; no threshold/time-window rescue inside EX061'
    }
    common.write(WORK / 'conclusion.json', conclusion)
    for name in ('compact_statistics.json', 'judgment.json', 'verification.json', 'conclusion.json',
                 'verify_results.py', 'write_judgment.py', 'deliver_study.py', 'report.md'):
        source = WORK / name
        media = 'text/x-python' if source.suffix == '.py' else 'text/markdown' if source.suffix == '.md' else 'application/json'
        ref = publish_evidence(ctx, MaterialEvidenceWrite(exp, source.stem.replace('_', '-'), source.read_bytes(), media, source.suffix[1:]))
        ref.resolve(ROOT)
        refs[name] = ref.to_dict()
        if source.suffix == '.py':
            shutil.copyfile(source, path / 'src' / name)
    evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(r) for r in refs.values()))
    for ref in evidence:
        ref.resolve(ROOT)
    entries = []
    for component_id, explanation in (
        ('LATE_RECOVERY', '主3/5日标签无足够稳定增量；保留全池3日四相位正相关与微小预测改善；机会池反向不足以授予正向策略资格'),
        ('EARLY_VOLUME_RECLAIM', '机会池高组收益反而较低；控制后弱、年份相位不稳且端点并列值限制量权重归因；反向仅为新待证假说线索')):
        test = d.ComponentTestResult(
            test_id=component_id + '-fixed-positive-study', experiment_id=exp.experiment_id,
            protocol=EvidenceRef.from_dict(refs['plan.json']), status=d.ComponentTestStatus.INEFFECTIVE,
            explanation=explanation, evidence=tuple(EvidenceRef.from_dict(refs[k]) for k in
                ('statistics.json', 'judgment.json', 'verification.json', 'conclusion.json')))
        entries.append(d.ComponentEntry(
            component_id=component_id,
            definition=d.ExperimentDefinitionRef(evidence=EvidenceRef.from_dict(refs['late_recovery_component.py']), entrypoint='build_features'),
            role='尾盘时序及早段价位量分配的潜在盈利机会信息；原预声明方向正向',
            label='return_3,return_5主；return_1辅助；downside_1,downside_3,downside_5配对风险',
            horizon='T+1 Open入场，T+1+h Open退出，持有h完整session；风险Low含entry、不含exit',
            control='固定14原方向/位置/量能/波动/路径/确认信息，4同样本训练ECDF ridge alpha10模型',
            availability='T全部8根30m完结，沿用daily T17政策，T+1执行；历史发布时间未独立验证',
            price_basis='HFQ_RESEARCH原2019-12-31 anchor0.2803；无现金分红叠加；标签非费用后账户收益',
            applicability='S013已见开发池1635信号日；全池主/原C8880事前资格机会池辅助；年度顺序不等于封存独立验证',
            judgment=explanation, tests=(test,)))
    mandate = d.DeliveryReference.from_dict(read(ROOT / 'research/S013/deliveries/MANDATE/6/receipt.json')['reference'])
    previous = d.DeliveryReference.from_dict(read(ROOT / 'research/S013/deliveries/COMPONENTS/2/receipt.json')['reference'])
    report = (WORK / 'report.md').read_text(encoding='utf-8')
    public_report = report + '\n## 正式证据引用\n\n'
    experiment_report = report + '\n## 正式证据引用\n\n'
    for name, value in refs.items():
        ref = EvidenceRef.from_dict(value)
        public_report += f'- [{name}]({ref.path})\n'
        experiment_report += f'- [{name}](../../../assets/deliveries/COMPONENTS/3/{ref.path})\n'
    receipt = assemble_delivery(
        ctx.repository,
        d.DeliveryDefinition(batch=ctx.batch, stage=d.DeliveryStage.COMPONENTS, revision=3, predecessors=(mandate, previous)),
        d.DeliveryContent(payload=d.ComponentPanel(tuple(entries), 'EX061固定正向机会假说缺乏充分增量；阶段二收尾，反向仅线索；未运行新账户，稳健策略目标未完成'),
                          status=d.DeliveryStatus.COMPLETE, facts=(), explanations=(), report=public_report, evidence=evidence))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    common.write(path / 'protocols/delivery_validation.json', validation.to_dict())
    common.write(path / 'protocols/delivery_reference.json', receipt.reference.to_dict())
    common.write(path / 'protocols/final_evidence_references.json', refs)
    (path / 'others').mkdir(exist_ok=True)
    (path / 'others/report.md').write_text(experiment_report, encoding='utf-8', newline='\n')
    assert validation.status.value == 'PASS', validation.to_dict()
    print({'phase_two': 'COMPLETE', 'FULL': validation.status.value, 'actual_checks': 152,
           'new_accounts': 0, 'strategy_goal_achieved': False, 'reference': receipt.reference.to_dict()}, flush=True)


if __name__ == '__main__':
    main()
