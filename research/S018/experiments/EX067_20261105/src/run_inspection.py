"""One exact native-V4 stage-five attempt; no optimization, freezing or production writes."""
from pathlib import Path
import os
import sys
import json
from hashlib import sha256
from datetime import date, datetime, timedelta
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[5]
EXP_ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / '.tmp/s018-c9380-stage5'
TMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TMP), TMP=str(TMP), PYTHONDONTWRITEBYTECODE='1',
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.dont_write_bytecode = True

from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    record_research_decision, describe_inspection_environment, inspect_candidate,
    CandidateInspectionRequest, EquityInspectionReplay, EquityInspectionProtocol,
    FreezeTarget, InspectionDataKind)
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef
from strategy_manager import StrategyRegistry, CandidateKey, CandidateEvidence
from strategy_manager import freeze_contracts as f
from strategy_runtime import EquityInputBinding, InspectionControl, ExecutionResources
from dataflows import ProviderConfig, EquityDataRequest, TimeInterval
from paper_trading_engine.equity_inspection import (EquityPteDecision, EquityPteReport,
    EquityPteRestart, EquityPteReconcile, EquityPteScenario, EquityPteInspectionProtocol)


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
    confirmation = save('protocols/user_selection.json', {
        'user_quote':'推进S018/C9380完成阶段五', 'recorded_on':'2026-11-05',
        'candidate':key.to_dict(), 'content_sha256':registration.content_sha256,
        'registration_sha256':registration.record_sha256,
        'scope':'选择原生V4 C9380执行阶段五隔离技术检验；不构成精确冻结包批准或生产部署授权',
        'source_deliveries':receipts})
    selection = record_research_decision(repo, f.ResearchDecision(
        'S018-select-C9380-stage5-20261105', 'S018', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(key,registration.content_sha256,registration.record_sha256),
        CandidateEvidence(confirmation.relative_to(ROOT).as_posix(),sha256(confirmation.read_bytes()).hexdigest()),
        '用户明确选择C9380推进阶段五；保持原生V4语义，未批准冻结或生产部署。'))
    save('others/inspection_selection.json',selection.to_dict())
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
    environment = describe_inspection_environment(repo)
    protocol = EquityInspectionProtocol('candidate-inspection-v2','ECONOMIC_V1',0.,
        EquityPteInspectionProtocol(environment,tuple(scenarios)))
    save('protocols/inspection_protocol.json',protocol.to_dict())
    save('others/inspection_inputs.json',{'source_account':source_path.relative_to(ROOT).as_posix(),
        'source_account_sha256':source_path.stem,'binding':binding.to_dict(),'verified_inputs':verified_inputs,
        'channel_anchor':{'account_sha256':account_path.stem,'order':order,'fill':fill},
        'planned_pte_coverage':['COMPLETED','PARTIAL','DUPLICATE','RESTART','REJECTED','UNKNOWN','EXPIRED','RECONCILIATION_BLOCKED'],
        'note':'PTE预期值由历史首笔买入及标准费用推导；是否满足原生V4通路由实际检验决定，未执行项不能视作通过。'})
    request = CandidateInspectionRequest(key,selection,context,experiment,
        FreezeTarget('v1',None,'S018 C9380原生V4首次阶段五技术检验',date(2026,10,30),date(2026,11,6)),
        protocol,(replay,),InspectionDataKind.HISTORICAL,
        remaining_risks=('V4原生发布与PTE能力须实际验证；不得降级到V2。',
            'forward_start仅冻结计划元数据，不构成生产部署或启动授权。',
            'PTE为隔离录制通道检验，历史输入与模拟通道报告的用途已分别说明。'))
    save('protocols/inspection_scope.json',{'candidate':key.to_dict(),'definition':candidate.definition.to_dict(),
        'target':request.target.to_dict(),'data_kind':request.data_kind.value,'max_workers':2,'timeout_seconds':180,
        'baseline':'NOT_REQUESTED','source_deliveries':receipts,'remaining_risks':list(request.remaining_risks)})
    report = inspect_candidate(repo,request,control=InspectionControl(max_workers=2,timeout_seconds=180))
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
        'behavior':report.behavior_equivalence.to_dict(),'pte':report.pte_runtime.to_dict()},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
