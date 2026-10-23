"""Append purpose-specific component evidence and close the authorized stage."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '1'
import json
from hashlib import sha256
from pathlib import Path
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    assemble_delivery, update_research_intent, ResearchIntentUpdate)
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef, MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]
BASE = HERE.parent


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def refs_in(value):
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef':
            yield EvidenceRef.from_dict(value)
        else:
            for child in value.values():
                yield from refs_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs_in(child)


def main():
    assert not (HERE / 'others/integrated_delivery.json').exists()
    repo = RepositoryContext.discover(ROOT); batch = ResearchBatchRef('S015')
    ctx = create_research_context(repo, batch, resources=ExecutionResources(4, 1, 13))
    published = {n: read(BASE / f'EX{n:03}_20261024/others/published_refs.json') for n in (48, 49, 50)}
    for item in published.values():
        assert item['validation']['status'] == 'PASS'
    previous_receipt = read(ROOT / 'research/S015/deliveries/COMPONENTS/12/receipt.json')
    old_path = ROOT / 'research/S015/assets/deliveries/COMPONENTS/12/delivery.json'
    assert sha256(old_path.read_bytes()).hexdigest() == next(row['sha256'] for row in previous_receipt['files'] if row['path'] == 'delivery.json')
    old = d.ComponentPanel.from_dict(read(old_path)['content']['payload'])

    def material(n, name):
        return EvidenceRef.from_dict(published[n]['materials'][name])

    def test(n, name, status, explanation):
        result_path = 'others/results.json'
        accounts = read(BASE / f'EX{n:03}_20261024' / result_path)['rows']
        return d.ComponentTestResult(name, f'EX{n:03}_20261024',
            material(n, 'protocols/accounts.json' if n == 49 else 'protocols/allocation.json'),
            d.ComponentTestStatus(status), explanation,
            (material(n, result_path), material(n, 'others/account_audit.json' if n == 49 else 'others/analysis.json'),
             *tuple(EvidenceRef.from_dict(row['evidence']) for row in accounts)))

    def entry(name, n, source, role, judgment, tests):
        return d.ComponentEntry(name, d.ExperimentDefinitionRef(material(n, source), 'intentions'), role,
            '三日事件/入场日金额与完整连续账户净收益、回撤、机会代价分别报告', '固定三日意图，434/415窗口各自10万元',
            '固定其他规则的组合/删项和简单基线；风险用途另有固定50%/75%/100%对照',
            'T收盘、T+1执行；份额主T−1及T−3敏感性，历史发布时间/修订PIT未认证',
            'HFQ_RESEARCH / DAILY_RANGE_V3，1%限价买、市价卖，每侧0.1%，signal_cash_fraction/entry_cycle',
            '同一已见开发池、同一学习日程和代表参数；不是独立样本或完整策略资格', judgment, tuple(tests))

    price_source = 'src/strategy_runtime/strategies/price_information.py'
    entries = [entry('share_screen_cycle_application', 49, price_source, '份额状态辅助三日收益筛选',
        '仅T−1量价背景有限支持；T−3显著退化，加入路径后是收益/风险取舍，禁止概括为普遍有效。', [
            test(49, 'funding-in-price-control-lag1', 'SUPPORTED', 'B→BF收益+12.1331pp、回撤−0.7827pp；适用该原型与T−1假设，未通过经济门。'),
            test(49, 'funding-in-price-control-lag3', 'INEFFECTIVE', 'T−3 BF收益0.420%、回撤32.723%，相对B同时更差；可得性反证。'),
            test(49, 'funding-on-price-path', 'INSUFFICIENT_DATA', 'BP→BPF收益−24.0553pp、回撤−4.8753pp；有取舍，不宣称联合改善。')]),
        entry('path_screen_cycle_application', 49, price_source, '路径信息在不同背景的收益筛选职责',
            '收益机会证据有条件，量价背景增加回撤；份额背景双向小幅改善，仍远离S011双门。', [
                test(49, 'path-on-price-control', 'SUPPORTED', 'B→BP收益+41.1724pp但回撤+3.7196pp，只支持收益机会职责。'),
                test(49, 'path-on-price-funding', 'SUPPORTED', 'BF→BPF收益+4.9840pp、回撤−0.3730pp，限该背景与T−1；不证明独立机制。'),
                test(49, 'event-versus-account-contradiction', 'INSUFFICIENT_DATA', 'BPF事件损失识别/盈利保留优于BP，但账户收益更低；事件统计不足以替代账户用途。')]),
        entry('volatility_cycle_allocation_application', 50, 'src/strategy_runtime/strategies/cycle_risk_allocation.py',
            '波动风险中位数作为入场拒绝或周期50%/100%分配',
            '停止该固定风险阈值直接分配路线；一般减仓解释足够，没有证实针对性优势。', [
                test(50, 'risk-reject-versus-constant-half', 'INEFFECTIVE', '拒绝收益0.226%/回撤20.855%，被固定50%的8.786%/15.683%同时超过。'),
                test(50, 'risk-half-versus-constant-three-quarter', 'INSUFFICIENT_DATA', '动态比固定75%多329元但多1.233pp回撤、平均敞口更高，优势未成立。'),
                test(50, 'entry-day-risk-opportunity-cost', 'INEFFECTIVE', '共同事件识别52.280%入场亏损，同时排除55.756%盈利；不支持该入场避损用途。')])]
    conclusion = '新资金契约阶段二完成：份额/路径有原型和时点受限的账户增量；风险拒绝/半仓用途没有成立。12配置24正式窗口均未通过联合中心，合格候选0；不自动进入阶段三。'
    panel = d.ComponentPanel((*old.components, *entries), conclusion)
    refs = list(refs_in(published))
    refs += list(refs_in(read(HERE / 'protocols/plan.json')['sources']))
    ex = ExperimentRef('S015', HERE.name)
    plan = ROOT / 'research/S015/materials/research_plan_20261024.md'
    for path in (Path(__file__), HERE / 'others/stage2_synthesis.md', plan):
        refs.append(publish_evidence(ctx, MaterialEvidenceWrite(ex, path.stem, path.read_bytes(),
            'text/x-python' if path.suffix == '.py' else 'text/markdown', path.suffix[1:])))
    report = (HERE / 'others/stage2_synthesis.md').read_text(encoding='utf-8')
    assembled = assemble_delivery(repo,
        d.DeliveryDefinition(batch, d.DeliveryStage.COMPONENTS, 13, (d.DeliveryReference.from_dict(previous_receipt['reference']),)),
        d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=tuple(dict.fromkeys(refs))),
        resources=ExecutionResources(4, 1, 13),
        on_progress=lambda event: print(event, flush=True))
    assert assembled.validation.status.value == 'PASS', assembled.validation.issues
    intent = read(ROOT / 'research/registrations/S015/family.json')['research_intent']
    preserved_candidates = intent.get('current_candidates')
    intent.update(current_components=assembled.receipt.reference.to_dict(),
        current_experiment=ExperimentRef('S015', 'EX050_20261024').to_dict(),
        current_diagnosis_report=published[48]['report'],
        current_phase='阶段二新资金契约固定对照完成：有限用途与反证已交付，联合中心0，等待阶段三决定',
        experiment_budget={'unlimited': True, 'authorized': None, 'completed': 3, 'remaining': None,
                           'source': refs[-1].to_dict(), 'scope': '本轮P0/P1/P2，12固定配置24正式窗口及4技术重复；P3未触发'},
        qualified_candidate_count=0, pending_selection_candidate_count=0, pending_freeze_candidate_count=0,
        next_gate='请用户决定是否进入阶段三完善价格路径机会/持有价值/资金占用结构；不自动继续份额或风险阈值搜索，不推进选型冻结。')
    assert intent.get('current_candidates') == preserved_candidates
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='完成用户批准的新资金契约阶段二固定对照；保留条件性增量、可得性反证及风险分配负面结果，资格仍0。')
    save(HERE / 'others/integrated_delivery.json', {'reference': assembled.receipt.reference.to_dict(),
        'validation': assembled.validation.to_dict(), 'preserved_entries': len(old.components), 'new_entries': len(entries),
        'total_entries': len(panel.components), 'new_purpose_tests': sum(len(c.tests) for c in entries),
        'new_configurations': 12, 'formal_window_scenarios': 24, 'technical_repeat_scenarios': 4,
        'qualified_candidates': 0, 'source_reports': {str(n): published[n]['report'] for n in published}})
    print('COMPONENTS13_FULL_PASS', assembled.receipt.reference.content_sha256, flush=True)


if __name__ == '__main__':
    main()
