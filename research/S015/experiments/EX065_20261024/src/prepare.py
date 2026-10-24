"""Publish the approved S015 mandate and bounded stage-three search design."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, assemble_delivery
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, ExecutionResources, MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX065_20261024')
HOME = EX.resolve(ROOT)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    assert not (HOME / 'others/mandate_reference.json').exists()
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))
    old_dir = ROOT / 'research/S015/assets/deliveries/MANDATE/4'
    old_bytes = (old_dir / 'delivery.json').read_bytes()
    old = d.DeliveryContent.from_dict(json.loads(old_bytes)['content'])
    predecessor = d.DeliveryReceipt.from_dict(read(old_dir / 'receipt.json')).reference
    assert predecessor.content_sha256 == 'c43e72867f5e0a3927c9adfaf11cb1d3b0c76e523a705b3ff054dc5b1546a6d4'
    auth = {
        'date': '2026-10-24', 'source': 'human message in this Codex conversation',
        'verbatim': '同意，合并回研究分支，然后按新规则修订S015研究约定，重新执行阶段三的参数寻优',
        'scope': 'Revise mandate; repeat stage-three parameter optimization. Stage-four execution, selection, freeze, PTE and production require separate approval.',
    }
    save(HOME / 'protocols/authorization.json', auth)
    plan = {
        'version': 'S015-stage3-joint-search-v1', 'stage': 3, 'seed': 13,
        'question': 'Does joint lookback/holding-time exploration uncover feasible configurations beyond the earlier cross-shaped search, and can sizing/rearm interaction improve them?',
        'hypothesis': 'Entry opportunity and the exit/re-entry schedule interact; sizing trades return for drawdown and cannot be treated as identifying losses.',
        'source': 'Exact EX062 price_process.py; mean center below-price entry; fixed intent-age exit.',
        'space': {'lookback': [2, 10], 'hold': [1, 14], 'allocation': [0.6, 1.0, 0.025], 'rearm_mode': ['positive_step', 'immediate']},
        'fixed': {'mode': 'center_below', 'exit_mode': 'fixed', 'center_kind': 'mean', 'max_hold': 30, 'confirmation': 1, 'failure_buffer': 0.0, 'concentration': 0.75, 'start': '2025-01-02'},
        'sequence': ['128 queued real-parameter trials: complete 9x14 time grid at 100% positive-step rearm, plus 95%/100% immediate-rearm controls at 3/3.', '96 adaptive multivariate constrained TPE suggestions in batches of 8; finish and tell each batch before asking the next; duplicates reuse exact same-run evidence.'],
        'budget': {'planned_trials': 224, 'maximum_new_configurations': 256, 'conditional_boundary_reserve': 32, 'maximum_formal_accounts': 512, 'technical_accounts': 2, 'workers': 8, 'native_threads': 1},
        'objectives': ['434 net return maximize', '434 drawdown minimize', '415 net return maximize', '415 drawdown minimize'],
        'constraints': 'Sampler receives violations of all original 434 center economic/frequency gates and 415 dual gates. Final eligibility is checked independently using original strict/inclusive inequalities; no weighted score.',
        'stopping': 'Complete grid and 96 adaptive trials, then inspect feasible/better frontier at artificial bounds. If improvement appears at hold14 or lookback10, use up to32 explicitly declared successor boundary controls, extending strategy guard only if necessary. Otherwise close with explored scope and remaining gaps, without claiming global optimum.',
        'historical_controls': ['EX061:C6105', 'EX061:C6104', 'EX061:C6101', 'EX061:C6102', 'CANDIDATES/6 all16 passing centers retained'],
        'history': 'No old trial is retrospectively called adaptive. EX064 negative joint-neighborhood evidence remains. New max_hold30 is inactive for fixed exits; confirm original3/3 account equivalence.',
        'data': 'Existing S015 authorized 434/415 windows through2026-10-21 only, separate100000 cash accounts; no new sources or data.',
        'execution': 'CYCLE_TARGET/signal_cash_fraction/entry_cycle; per-side0.1%;1%limitbuy/marketexit;100-share lots; no terminal liquidation.',
        'stage4': 'Not executed here. 5%local cap is NOT the stage3 search domain. New designs keep over-limit parameters fixed; genuine whole-item nonapplicability retains empty measurements and minimum ranking scores.',
        'limitations': 'Repeatedly seen overlapping development windows; no independent validation. Fixed exit family only; existing confirmed-guard candidates remain controls, not declared globally optimized.',
    }
    plan['dependency_files'] = {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in (
        'research/S015/experiments/EX062_20261024/src/accounts.py',
        'research/S015/experiments/EX016_20261023/src/suite.py',
        'research/S015/experiments/EX061_20261024/src/account_audit.py',
    )}
    save(HOME / 'protocols/search.json', plan)
    method = {
        'version': 'S015-bounded-local-applicability-v2',
        'relative_change_cap': 0.05, 'inclusive': True,
        'discrete': 'Nearest lawful changes checked separately in each direction. Over-cap directions excluded; retain center and disclose uncovered parameter-selection risk.',
        'continuous': 'Use legal +/-5%relative endpoints; never confuse with five percentage points. Zero or nonratio scales require prospectively justified absolute limits.',
        'enumeration': 'Complete legal Cartesian product of applicable axes, excluding center; no post-outcome dropping.',
        'whole_item_not_applicable': 'Requires complete applicability evidence; not PASS or FAIL. No fake accounts, quantiles or0/0ratio. Other checks remain required.',
        'ranking': 'Original center return/drawdown Pareto layers first; within-layer both parameter metrics get minimum valid ranking treatment for whole-item nonapplicability. Raw measurements remain absent; actual missing/failing evidence is not exempt.',
        'unchanged_targets': 'All economic, frequency, fee-stress and415S011 dual-superiority targets, including existing13/16 parameter target, remain exactly unchanged.',
        'history': 'Old mandate and assessments unchanged. Future assessment uses a new protocol/revision and discloses prior failed out-of-cap results without adding diagnostic vetoes.',
    }
    save(HOME / 'protocols/parameter_method.json', method)
    target = HOME / 'src/strategy_runtime/strategies/price_process.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'research/S015/experiments/EX062_20261024/src/strategy_runtime/strategies/price_process.py'
    shutil.copyfile(source, target)
    assert target.read_bytes() == source.read_bytes()
    refs = []
    def publish(path):
        ref = publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(),
            {'.json': 'application/json', '.py': 'text/x-python', '.md': 'text/markdown'}[path.suffix], path.suffix[1:]))
        refs.append(ref)
        return ref
    auth_ref = publish(HOME / 'protocols/authorization.json')
    confirmation = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, auth_ref)
    items = []
    for item in old.payload.items:
        if item.item_id == 'performance':
            item = replace(item, statement='经济、频率及费用压力目标全部保持；参数自检仅在5%相对上限内展开合法联合邻域。整项不适用不判通过或失败，其他目标仍须达标；两项敏感度按最低得分参与原排序。', confirmation=confirmation)
        elif item.item_id == 'current-authorization':
            item = replace(item, statement='用户批准按新适用性规则修订S015研究约定并重新执行阶段三参数寻优。沿用既有数据、窗口和经济目标；阶段四、选型、冻结及生产另行确认。', confirmation=confirmation)
        items.append(item)
    payload = d.ResearchMandate(tuple(items))
    assert all(a.requirement == b.requirement for a, b in zip(old.payload.items, payload.items, strict=True))
    changed = [a.item_id for a, b in zip(old.payload.items, payload.items, strict=True) if a != b]
    assert changed == ['performance', 'current-authorization']
    report = '''# S015研究约定修订5：限幅适用性与阶段三重新寻优

用户批准合并平台修改、按新规则修订约定，并重新执行阶段三参数寻优。

434日开发窗口、415日固定S011双优比较、全部中心经济与频率、邻点经济及费用压力目标保持原始精确值。
参数自检默认相对上限5%，按真实单位和最小合法变化分别判断方向；超限参数保持中心值，不为豁免补做机制诊断。整项不适用不记通过或失败，其余自检照常；两项参数指标在原有中心帕累托分层后的同层排序中取最低有效得分，原始分位数为空。缺失、错误或计算失败不属于不适用。

本修订不重写[MANDATE/4](../4/report.md)或历史ASSESSMENT。后续自检另立协议和评价，保留EX064超限参数扰动的失败事实。当前尚无完成新规则全项自检的候选。

阶段三的寻优范围不受阶段四5%局部上限限制。本轮采用完整联合时间参数网格与分批自适应TPE，明确真实生效参数、约束、预算、边界和停止条件；不将固定配置排队称为自适应优化，不以工具名称证明搜索充分。

授权范围仅为研究约定修订与阶段三参数寻优；不自动执行阶段四、选型、冻结、PTE或生产。数据已被反复观察，434/415窗口高度重叠，不构成独立验证。
'''
    (HOME / 'protocols/mandate_revision.md').write_text(report, encoding='utf-8')
    save(HOME / 'others/mandate.json', payload.to_dict())
    for path in (HOME / 'protocols/parameter_method.json', HOME / 'protocols/search.json', HOME / 'protocols/mandate_revision.md', HOME / 'others/mandate.json', Path(__file__), HOME / 'src/search.py', target):
        publish(path)
    assembled = assemble_delivery(repo, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.MANDATE, 5, (predecessor,)),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=tuple((*old.evidence, *refs))), resources=ExecutionResources(1, 1, 13))
    assert assembled.validation.status.value == 'PASS'
    assert (old_dir / 'delivery.json').read_bytes() == old_bytes
    save(HOME / 'others/mandate_reference.json', assembled.receipt.reference.to_dict())
    save(HOME / 'others/mandate_validation.json', assembled.validation.to_dict())
    save(HOME / 'others/protocol_refs.json', [x.to_dict() for x in refs])
    print('MANDATE5_FULL_PASS', assembled.receipt.reference.content_sha256, flush=True)


if __name__ == '__main__':
    main()
