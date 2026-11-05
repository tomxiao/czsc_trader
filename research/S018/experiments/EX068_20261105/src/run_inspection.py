"""One exact native-V4 stage-five attempt; no optimization, freezing or production writes."""
# ruff: noqa: E402 -- Set subprocess and temporary-directory policy before platform imports.
from pathlib import Path
import os
import sys
import json
from hashlib import sha256
from datetime import date, datetime, timedelta
from decimal import Decimal
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[5]
EXP_ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / '.tmp/s018-c9380-stage5'
TMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TMP), TMP=str(TMP), PYTHONDONTWRITEBYTECODE='1',
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.dont_write_bytecode = True

from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    describe_inspection_environment, inspect_candidate,
    CandidateInspectionRequest, EquityInspectionReplay, EquityInspectionProtocol,
    FreezeTarget, InspectionDataKind)
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef
from strategy_manager import StrategyRegistry, CandidateKey
from strategy_manager import freeze_contracts as f
from strategy_runtime import EquityInputBinding, InspectionControl, ExecutionResources
from dataflows import ProviderConfig, EquityDataRequest, TimeInterval
from paper_trading_engine.equity_inspection import (EquityPteDecision, EquityPteReport,
    EquityPteRestart, EquityPteReconcile, EquityPteScenario, EquityPteInspectionProtocol, EquityPteAction, EquityPteSettle)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(relative, value):
    path = EXP_ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
    return path


def main():
    repo = RepositoryContext.discover(ROOT)
    experiment = ExperimentRef('S018', EXP_ROOT.name)
    key = CandidateKey('S018', 'C9380')
    candidate = load_candidate(repo, key)
    registration = StrategyRegistry(repo.research_registry_root).get_candidate_registration(key)
    assert registration.content_sha256 == '186dffc6fe4df3aec1638030d7c0f65d594b6c9578593c39b5676796fe3c5d4a'
    assert candidate.definition.contract_version == 4
    evidence_dir = ROOT / 'research/S018/assets/evidence/EX064_20261104'
    source_path = evidence_dir / 'b2a1d6c30c1a1b0c65b633de3d8f6d6cd08cdf534214c397c4a66f6cfaf15d92.json'
    assert sha256(source_path.read_bytes()).hexdigest() == source_path.stem
    source = read(source_path)
    assert source['request']['candidate_definition'] == json.loads(json.dumps(candidate.definition.to_dict()))
    assert source['request']['content_sha256'] == registration.content_sha256
    receipts = {}
    for name, revision in [('CANDIDATES',3), ('ASSESSMENT',2)]:
        path = ROOT / f'research/S018/deliveries/{name}/{revision}/receipt.json'
        receipt = read(path)
        receipts[name] = {'path': path.relative_to(ROOT).as_posix(),
            'file_sha256':sha256(path.read_bytes()).hexdigest(), 'reference':receipt['reference']}
    assert receipts['ASSESSMENT']['reference']['content_sha256'] == '15bf59b4fc8eb863b702dca65adb11d560e2aa0fbc96b3ee0d0519f7a24274aa'
    selection = f.DecisionReference.from_dict(read(ROOT / 'research/S018/experiments/EX067_20261105/others/inspection_selection.json'))
    save('others/inspection_selection.json',selection.to_dict())
    save('protocols/continuation_authorization.json', {
        'user_reply':'同意', 'recorded_on':'2026-11-05',
        'approved_proposal':'切回RSCH，更新检验协议中的公司行动步骤和金额精度，正式推进S018/C9380阶段五。',
        'candidate':key.to_dict(), 'content_sha256':registration.content_sha256,
        'scope':'继续阶段五正式技术检验；精确冻结计划产生后另行呈请批准；不部署。',
        'original_selection':selection.to_dict(), 'platform_commit':'57f925496'})
    binding = EquityInputBinding.from_dict(source['request']['input_binding'])
    requests = tuple(dict.fromkeys(EquityDataRequest(p.instrument,p.source,p.query) for _,p in binding.request_bindings))
    context = create_research_context(repo,ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={},equity_bindings={}),
        execution_spec=candidate.definition.execution_spec,resources=ExecutionResources(2,1,17))
    verified_inputs = []
    for role, query in binding.bind_requests(requests):
        result = context.data.fetch(query,prepared=binding.prepared)
        assert result.ready, result.error
        assert result.identity.content_sha256 == binding.expected_identities[role]
        verified_inputs.append({'role':role,'sha256':result.identity.content_sha256,'rows':len(result.dataframe)})
    interval = TimeInterval(*(datetime.fromisoformat(source['request']['window'][k]) for k in ['start','end']))
    replay = EquityInspectionReplay(f.InspectionCoordinate('MU_DEVELOPMENT','STANDARD'),binding,requests,
        interval,source['request']['initial_cash'],source['request']['fee_rate'])
    # Recorded channel scenarios use the first real historical buy as their sizing/price anchor.
    # They are planned injected reports, not assertions that production orders occurred.
    account_path = evidence_dir / (source['candidate_ref']['sha256']+'.json')
    assert sha256(account_path.read_bytes()).hexdigest() == account_path.stem
    run = read(account_path)['run']
    order, fill = run['orders'][0], run['fills'][0]
    channel_anchor = {'account_sha256':account_path.stem,'order':order,'fill':fill}
    assert order['side'] == fill['side'] == 'BUY' and order['order_id'] == fill['order_id']
    start,end = (datetime.fromisoformat(order[k].replace('Z','+00:00')) for k in ['valid_start','valid_end'])
    buy_interval = TimeInterval(start,end)
    cash,fee = Decimal(str(replay.initial_cash)),Decimal(str(replay.one_way_cost))
    quantity,price = int(fill['quantity']),Decimal(str(fill['price']))
    partial = EquityPteReport(0,1,price,start+timedelta(minutes=1),'FILLED_PART')
    complete = EquityPteReport(0,quantity,price,start+timedelta(minutes=2),'FILLED_ALL')
    reconcile = EquityPteReconcile(cash,0)
    scenarios = [EquityPteScenario('historical-first-buy-partial-duplicate-restart',
        (reconcile,EquityPteDecision(buy_interval,start),partial,partial,EquityPteRestart(),complete),
        cash-quantity*price*(1+fee),quantity,Decimal(0))]
    reserved = quantity*Decimal(str(order['limit_price']))*(1+fee)
    for code,outcome,at in [('REJECTED','REJECTED',start),('UNKNOWN','UNKNOWN',start),('EXPIRED','ACCEPTED',end)]:
        scenarios.append(EquityPteScenario(code.lower(),
            (reconcile,EquityPteDecision(buy_interval,at,outcome,code)),
            cash if code == 'REJECTED' else cash-reserved,0,Decimal(0)))
    scenarios.append(EquityPteScenario('reconciliation-blocked',
        (EquityPteReconcile(cash-1,0),EquityPteDecision(buy_interval,start,expected='RECONCILIATION_BLOCKED')),
        cash,0,Decimal(0)))
    quantum = Decimal('0.0001')
    pte = EquityPteInspectionProtocol(describe_inspection_environment(repo),
        tuple(replace(s,expected_cash=s.expected_cash.quantize(quantum)) for s in scenarios))
    # Full recorded cycles exercise state persistence, hold, add and close after restart.
    # These channel facts originate from the retained historical model, not live broker trades.
    account_run = run
    end = datetime.fromisoformat(account_run['trades'][1]['exit_at'].replace('Z', '+00:00'))
    steps = [EquityPteReconcile(Decimal(str(replay.initial_cash)), 0)]
    expected_cash = Decimal(str(replay.initial_cash))
    quantity = order_index = 0
    fees = Decimal(str(replay.one_way_cost))
    for decision in account_run['decisions']:
        start = datetime.fromisoformat(decision['execution_start'].replace('Z', '+00:00'))
        stop = datetime.fromisoformat(decision['execution_end'].replace('Z', '+00:00'))
        if stop > end:
            break
        orders = [item for item in account_run['orders'] if item['decision_id'] == decision['decision_id']]
        steps.append(EquityPteDecision(TimeInterval(start, stop), start, expected='SUBMITTED' if orders else 'NO_ORDER'))
        for order in orders:
            fills = [item for item in account_run['fills'] if item['order_id'] == order['order_id']]
            assert len(fills) == 1 and order['status'] == 'FILLED'
            fill = fills[0]
            price, count = Decimal(str(fill['price'])), int(fill['quantity'])
            steps.append(EquityPteReport(order_index, count, price, start + timedelta(minutes=1), 'FILLED_ALL'))
            steps.append(EquityPteRestart())
            fee = (count * price * fees).quantize(quantum)
            expected_cash = (expected_cash + (count * price if order['side'] == 'SELL' else -count * price) - fee).quantize(quantum)
            quantity += count if order['side'] == 'BUY' else -count
            order_index += 1
    assert quantity == 0 and order_index >= 5
    pte = replace(pte, scenarios=(*pte.scenarios, EquityPteScenario('recorded-two-cycles-with-add',
        tuple(steps), expected_cash, quantity, Decimal(0))))
    action_request, = [q for role, q in binding.bind_requests(requests) if role == 'actions']
    actions = context.data.fetch(action_request, prepared=binding.prepared).dataframe
    def with_known_actions(scenario):
        steps, seen = [], set()
        for step in scenario.steps:
            if type(step) is EquityPteDecision:
                for row in actions.itertuples():
                    if row.Kind == 'NONE' or row.EventId in seen or max(row.Date, row.AvailableDate) > step.interval.start:
                        continue
                    steps.append(EquityPteAction(str(row.EventId), str(row.Kind), row.Date.to_pydatetime(),
                        row.AvailableDate.to_pydatetime(), binding.expected_identities['actions'],
                        ratio=Decimal(str(row.Ratio)) if row.Kind == 'SPLIT' else None,
                        cash_per_share=Decimal(str(row.CashPerShare)) if row.Kind == 'CASH_DIVIDEND' else None,
                        pay_at=None if row.Kind != 'CASH_DIVIDEND' else row.PayAt.to_pydatetime()))
                    seen.add(row.EventId)
                steps.append(EquityPteSettle(step.interval.start))
            steps.append(step)
        return replace(scenario, steps=tuple(steps))
    pte = replace(pte, scenarios=tuple(with_known_actions(s) for s in pte.scenarios))
    protocol = EquityInspectionProtocol('candidate-inspection-v4','ECONOMIC_V1',0.,pte)
    save('protocols/inspection_protocol.json',protocol.to_dict())
    save('others/inspection_inputs.json',{'source_account':source_path.relative_to(ROOT).as_posix(),
        'source_account_sha256':source_path.stem,'binding':binding.to_dict(),'verified_inputs':verified_inputs,
        'channel_anchor':channel_anchor,
        'planned_pte_coverage':['COMPLETED','PARTIAL','DUPLICATE','RESTART','REJECTED','UNKNOWN','EXPIRED','RECONCILIATION_BLOCKED'],
        'money_quantum':'0.0001','continuous_cycle_fills':order_index,
        'note':'PTE录制回报来自原历史账户，以平台四位金额精度逐笔计费；补齐已知公司行动及到期支付，覆盖连续两周期含补仓；不代表券商真实成交。'})
    request = CandidateInspectionRequest(key,selection,context,experiment,
        FreezeTarget('v1',None,'S018 C9380原生V4首次冻结：保持已选参数及执行合同',date(2026,10,30),date(2026,11,6)),
        protocol,(replay,),InspectionDataKind.HISTORICAL,
        remaining_risks=('本次覆盖原生V4隔离检验及首次冻结；富途美股通道、旧策略升级和生产生效尚未实施。',
            'forward_start仅冻结计划元数据，不构成生产部署或启动授权。',
            'PTE为隔离录制通道检验，历史输入与模拟通道报告的用途已分别说明。'))
    save('protocols/inspection_scope.json',{'candidate':key.to_dict(),'definition':candidate.definition.to_dict(),
        'target':request.target.to_dict(),'data_kind':request.data_kind.value,'max_workers':2,'timeout_seconds':240,
        'baseline':'NOT_REQUESTED','source_deliveries':receipts,'remaining_risks':list(request.remaining_risks)})
    if (EXP_ROOT/'others/inspection_report.json').exists():
        raise RuntimeError('existing inspection result must not be overwritten')
    report = inspect_candidate(repo,request,control=InspectionControl(max_workers=2,timeout_seconds=240))
    save('others/inspection_report.json',report.to_dict())
    save('others/inspection_reference.json',report.reference.to_dict())
    from czsc_trader.application.research_evidence import validate_inspection
    validated = validate_inspection(ROOT,report.reference)
    assert validated == report
    save('others/inspection_validation.json',{'validated':True,'status':report.status.value,
        'reference':report.reference.to_dict(),
        'plan_sha256':None if report.plan is None else report.plan.sha256,
        'release':None if report.release is None else report.release.to_dict(),
        'registration_sha256':report.origin.registration_sha256})
    print(json.dumps({'status':report.status.value,'reference':report.reference.to_dict(),
        'behavior':report.behavior_equivalence.status.value,'pte':report.pte_runtime.status.value,
        'plan':None if report.plan is None else report.plan.sha256},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
