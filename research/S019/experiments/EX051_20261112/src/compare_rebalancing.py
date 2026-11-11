"""Compare two C1010 sizing policies using the same historical account engine."""

from collections import Counter
from dataclasses import asdict, replace
from decimal import Decimal
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.application import account_replay
from czsc_trader.research_tools import equity_replay
from execution_channels.contracts import ReplayOrder
from execution_channels.planning.result import PlanningConstraint, PlanningResult, PlanningStatus
from execution_channels.session_contracts import OrderSide, OrderType
from strategy_evaluator.equity_v4 import audit_account_v4


WORK = Path(__file__).resolve().parents[1]
ROOT = next(path for path in WORK.parents if (path / 'research/RSCH_AGENT.md').is_file())
PRIOR = WORK.parent / 'EX050_20261111'
sys.path.insert(0, str(PRIOR / 'src'))
import validate_v4_migration as migration


core = migration.core
ORIGINAL_PLAN = account_replay.execution_plan


class ReduceOnlyPlanner:
    """Local counterfactual planner. The normal EC planner owns entry and exit."""

    def __init__(self):
        self.entry_quantity = None

    def __call__(self, result, account, specification, **kwargs):
        plan = ORIGINAL_PLAN(result, account, specification, **kwargs)
        if not account.quantity:
            self.entry_quantity = None
            return plan
        if self.entry_quantity is None:
            self.entry_quantity = account.quantity
        if result.suppressed or result.proposal.decision.target == 0:
            return plan
        if specification.quantity_step != 1 or plan.cycle_before or plan.cycle_after or plan.legs:
            raise ValueError('C1010 diagnostic requires one-share units and direct orders')
        risk = result.proposal.cycle_values.get('risk_fraction')
        if not 0 < risk <= 1:
            raise ValueError('invalid live C1010 risk fraction')
        # Keep the final unit until the strategy itself calls for liquidation.
        cap = max(1, int(self.entry_quantity * Decimal(str(risk))))
        desired = min(cap, account.quantity)
        amount = min(account.quantity - desired, account.sellable_quantity)
        orders = (ReplayOrder(OrderSide.SELL, amount, OrderType.MARKET),) if amount else ()
        planned = account.quantity - amount
        if planned > desired:
            reasons = (PlanningConstraint.INSUFFICIENT_SELLABLE_QUANTITY,)
            status = PlanningStatus.CONSTRAINED if amount else PlanningStatus.BLOCKED
        else:
            reasons = ()
            status = PlanningStatus.READY if amount else PlanningStatus.NO_CHANGE
        identity = sha256(f'{plan.plan_identity}:ATR_REDUCE_ONLY:{self.entry_quantity}:{cap}:{planned}'.encode()).hexdigest()
        evidence = dict(plan.evidence, planning_mode='ATR_REDUCE_ONLY', sizing='EXPLICIT_ORDERS',
                        desired_quantity=desired, initial_fill_quantity=self.entry_quantity, risk_share_cap=cap,
                        planning_result=PlanningResult(status, reasons, desired, planned).to_dict())
        return replace(plan, plan_identity=identity, target_quantity=planned, orders=orders, evidence=evidence)


def authenticated_account(pointer):
    path, digest, header = migration.published_header(core.read(pointer))
    item = header['candidate_ref']
    raw = path.with_name(item['sha256'] + '.json').read_bytes()
    if sha256(raw).hexdigest() != item['sha256']:
        raise ValueError('control ledger hash differs from published evidence')
    return digest, header, raw


def audit_reduction(run):
    """Independently verify the share rule using confirmed positions and the fill journal."""
    by_decision = {fill['order_id'].rsplit(':', 1)[0]: fill for fill in run['fills']}
    assert len(by_decision) == len(run['fills'])
    quantity = 0
    entry_quantity = 0
    sells = Counter()
    entries = []
    active_bars = 0
    for decision, point in zip(run['decisions'], run['account_points'], strict=True):
        evidence = decision['plan']['evidence']
        fill = by_decision.get(decision['decision_id'])
        if quantity and decision['target'] > 0 and decision['signal_status'] == 'EVALUATED':
            facts = {item['key']: item['text'] for item in decision['explanation']['basis']}
            cap = max(1, int(entry_quantity * Decimal(facts['risk_fraction'])))
            assert evidence['planning_mode'] == 'ATR_REDUCE_ONLY'
            assert evidence['initial_fill_quantity'] == entry_quantity and evidence['risk_share_cap'] == cap
            assert decision['target_quantity'] == min(quantity, cap)
            active_bars += 1
        if fill:
            if fill['side'] == 'BUY':
                assert quantity == 0
                quantity = entry_quantity = fill['quantity']
                entries.append(fill['interval_start'])
            else:
                assert fill['side'] == 'SELL'
                quantity -= fill['quantity']
                reason = decision['explanation']['judgment'] if not quantity else 'ATR_PARTIAL'
                sells[reason] += 1
        assert quantity == point['quantity'] and quantity >= 0
    return {'entries': entries, 'sell_fills_by_reason': dict(sells),
            'active_bars_checked': active_bars, 'end_quantity': quantity}


def metrics(run, benchmark_dd):
    report = core.metrics(run, benchmark_dd)
    report.update(fills=len(run['fills']), buy_fills=sum(x['side'] == 'BUY' for x in run['fills']),
                  turnover_dollars=sum(x['quantity'] * x['price'] for x in run['fills']),
                  terminal_equity=run['account_daily'][-1]['equity'])
    report['sell_fills'] = report['fills'] - report['buy_fills']
    return report


def run_pair(context, experiment, execution, candidate, pressure, center, benchmark_dd, keep):
    label = 'STRESS' if pressure else 'STANDARD'
    pointer = PRIOR / 'others' / f"C1010_{'STRESS' if pressure else 'CENTER'}_account.json"
    control_digest, header, published = authenticated_account(pointer)
    request = migration.previous.request_for(experiment, candidate, pressure)
    prepared = context.evaluation.prepare(request, execution=execution)
    state = equity_replay._state(context.evaluation, execution)
    candidate, observations = equity_replay._replay(state, prepared)
    output = equity_replay._account_output_context(state, prepared, benchmark=False)
    assert header['request']['fee_rate'] == request.fee_rate
    assert header['request']['initial_cash'] == request.initial_cash
    assert header['input_ref']['sha256'] == output.input_sha256
    assert candidate.definition.execution_input is None
    assert header['request']['candidate_definition'] == center['definition']
    contract = equity_replay._ReplayAccountRequest(request.window, request.initial_cash, request.fee_rate,
        migration.StrategyPerformanceBudget(max_seconds_per_1000_calls=.5))
    owner = equity_replay._account_owner(prepared, benchmark=False)

    started = perf_counter()
    control, _ = equity_replay._compute_account(observations, candidate, contract, owner, None, output)
    expected = migration.normalized_account(published)
    assert migration.normalized_account(control.content) == expected, f'{label} original replay parity failed'
    print(label, 'CONTROL_PARITY_PASS', round(perf_counter() - started, 2), flush=True)

    with patch.object(account_replay, 'execution_plan', ReduceOnlyPlanner()):
        variant, timing = equity_replay._compute_account(observations, candidate, contract, owner, None, output)
    run = json.loads(variant.content)['run']
    baseline = json.loads(published)['run']
    products = json.loads(prepared.snapshot.artifact.content)['products']
    fields = ('decisions', 'orders', 'fills', 'account_entries', 'account_points', 'trades', 'price_basis', 'quantity_basis')
    audited = audit_account_v4(initial_cash=request.initial_cash, specification=center['definition']['execution_spec'],
        bars=products['bars'], constraints=products['constraints'], fee_rate=request.fee_rate,
        **{name: run[name] for name in fields})
    assert audited.sessions == 1212 and len(run['decisions']) == 15702
    assert abs(audited.annualized_return - run['metrics']['annualized_return']) < 1e-10
    assert abs(audited.daily_max_drawdown - run['metrics']['daily_max_drawdown']) < 1e-10
    assert audited.closed_cycles == run['metrics']['closed_cycles']
    verification = audit_reduction(run)
    original_entries = {}
    for fill in baseline['fills']:
        if fill['side'] == 'BUY':
            original_entries.setdefault(fill['cycle_id'], fill['interval_start'])
    original_exits = [row['exit_at'] for row in baseline['trades']]
    variant_exits = [row['exit_at'] for row in run['trades']]
    a, b = metrics(baseline, benchmark_dd), metrics(run, benchmark_dd)
    ledger = core.d.MaterialEvidenceWrite(experiment, f'{label.lower()}-atr-reduce-only-ledger',
        gzip.compress(variant.content, compresslevel=5, mtime=0), 'application/gzip', 'gz')
    ref = publish_evidence(context, ledger, execution=execution)
    keep.append(ref)
    result = {'fee_rate': request.fee_rate, 'control_report': control_digest,
              'control_ledger': header['candidate_ref']['sha256'], 'normalized_control': expected['normalized_sha256'],
              'input_sha256': output.input_sha256, 'diagnostic_ledger': ref.to_dict(),
              'diagnostic_ledger_sha256_uncompressed': variant.sha256, 'baseline': a, 'reduce_only': b,
              'entry_intervals_equal': list(original_entries.values()) == verification.pop('entries'),
              'closed_exit_intervals_equal': original_exits == variant_exits, 'sizing_audit': verification,
              'ledger_audit': asdict(audited), 'replay_seconds': timing.replay_seconds}
    print(label, 'DIAGNOSTIC_AUDIT_PASS', {k: b[k] for k in ('nar', 'drawdown', 'calmar', 'fills', 'fees')},
          flush=True)
    return result


def report_text(summary):
    rows = ['# C1010 持仓再平衡对照', '',
            '本实验以 C1010 原策略为共同信号，使用同一批次 2022-01-03 至 2026-10-30 的 1,212 个交易日、'
            '15,702 个决策点和 10 万美元初始资金。买入限价、卖出市价、ATR 和期限保持一致。', '',
            '固定股数版本以实际入场成交股数为上限。持仓上限等于入场股数乘以 ATR 风险系数后向下取整，'
            '风险系数仍大于零时至少保留一股。现有股数高于上限时卖出，ATR 归零或持有到期时清仓。'
            '回放以原平台的 SRT 信号、EC 成交与账户记账、SE 统计为基础，只在本实验进程替换持仓订单计划。', '',
            '| 单边费用 | 持仓方式 | NAR | MDD（日末） | Calmar | 成交笔数 | 总费用（美元） |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for case in summary['cases'].values():
        for key, name in (('baseline', '每30分钟维持权重'), ('reduce_only', '仅按ATR减股')):
            m = case[key]
            rows.append(f"| {case['fee_rate']:.1%} | {name} | {m['nar']:.4%} | {m['drawdown']:.4%} | "
                        f"{m['calmar']:.6f} | {m['fills']} | {m['fees']:,.2f} |")
    rows.extend(['', '## 核验', ''])
    for key, case in summary['cases'].items():
        rows.append(f"- {key} 原版与既有账本完成全账本归一化等价验证。诊断账本通过独立账户审计与逐决策股数核验。"
                    f"入场区间一致性为 {case['entry_intervals_equal']}，"
                    f"已闭合周期退出区间一致性为 {case['closed_exit_intervals_equal']}。")
    rows.extend(['', '本实验用于解释已见历史中的再平衡贡献。候选身份及原阶段四评估沿用既有记录。', '',
                 '完整结构化结果见 [comparison.json](others/comparison.json)。', ''])
    return '\n'.join(rows)


def main():
    scratch = ROOT / '.tmp/s019-c1010-rebalancing'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ.update(TMP=str(scratch), TEMP=str(scratch))
    experiment = core.d.ExperimentRef.from_dict(core.read(WORK / 'experiment.json'))
    center, = (item for item in core.read(PRIOR / 'protocols/centers.json') if item['id'] == 'C1010')
    old = core.read(PRIOR / 'others/C1010_CENTER_account.json')
    stress = core.read(PRIOR / 'others/C1010_STRESS_account.json')
    candidate = migration.new_candidate(center, 'C1010', json.loads(center['definition']['parameters_json']))
    repository = core.RepositoryContext.discover(ROOT, explicit_root=ROOT)
    context = core.replay_context(repository, candidate.definition.execution_spec)
    keep = [core.d.EvidenceRef.from_dict(pointer) for pointer in (old, stress)]
    summary = {'kind': 'C1010_REBALANCING_COUNTERFACTUAL', 'cases': {}}
    with core.d.ResearchExecutionSession(context, experiment=experiment) as execution:
        for pressure, key in ((False, 'standard'), (True, 'stress')):
            base = stress if pressure else old
            ref = core.d.EvidenceRef.from_dict(base)
            head = core.read(ref.resolve(ROOT))
            benchmark_id = head['benchmark_ref']['sha256']
            raw = ref.resolve(ROOT).with_name(benchmark_id + '.json').read_bytes()
            assert sha256(raw).hexdigest() == benchmark_id
            benchmark_dd = json.loads(raw)['run']['metrics']['daily_max_drawdown']
            summary['cases'][key] = run_pair(context, experiment, execution, candidate, pressure, center, benchmark_dd, keep)
            core.immutable(WORK / 'others' / f'{key}.json', summary['cases'][key], scratch)
        core.immutable(WORK / 'others/comparison.json', summary, scratch)
        keep.append(publish_evidence(context, core.d.MaterialEvidenceWrite(experiment, 'comparison',
            core.encoded(summary), 'application/json', 'json'), execution=execution))
        report = report_text(summary).encode('utf-8')
        (WORK / 'report.md').write_bytes(report)
        publish_evidence(context, core.d.ExperimentReportWrite(experiment, sha256(report).hexdigest(),
            core.d.ExperimentOutcome.COMPLETED, tuple(keep)), execution=execution)
    validation = validate_experiment(repository, core.d.ExperimentValidationRequest(
        experiment, core.d.ExperimentValidationScope.REPORT_PUBLICATION))
    core.immutable(WORK / 'others/validation.json', validation.to_dict(), scratch)
    assert validation.status.value == 'PASS', validation
    print('COMPLETE', experiment.experiment_id, flush=True)


if __name__ == '__main__':
    main()
