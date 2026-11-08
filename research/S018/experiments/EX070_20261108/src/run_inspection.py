"""C9396 formal-component inspection; retained DFLS inputs, no freeze or deployment."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys
import json
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import argparse

ROOT = Path(__file__).resolve().parents[5]
EXP = Path(__file__).resolve().parents[1]
PRIOR = ROOT / 'research/S018/experiments/EX069_20261108'
TEMP = ROOT / '.tmp/s018-c9396-formal'
TEMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TEMP), TMP=str(TEMP), PYTHONDONTWRITEBYTECODE='1',
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.dont_write_bytecode = True
sys.path.insert(0, str(PRIOR / 'src'))

from data_inputs import build_data_context
from czsc_trader.application import (RepositoryContext, load_candidate, record_research_decision,
    describe_inspection_environment, inspect_candidate, CandidateInspectionRequest,
    EquityInspectionReplay, EquityInspectionProtocol, FreezeTarget, InspectionDataKind)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import ExperimentRef
from strategy_manager import StrategyRegistry, CandidateKey, CandidateEvidence
from strategy_manager import freeze_contracts as f
from strategy_runtime import EquityInputBinding, InspectionControl
from paper_trading_engine.execution_reference import ExecutionReferenceBinding
from paper_trading_engine.equity_inspection import (EquityPteDecision, EquityPteReport,
    EquityPteRestart, EquityPteReconcile, EquityPteScenario, EquityPteInspectionProtocol)
from dataflows import EquityDataRequest, TimeInterval

CONTENT = '94bbd13ea036128a0ce31c183b34da8fedfa742cb686132c85c0edb437bfd23b'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8', newline='\n')


def interval_of(row):
    return TimeInterval(datetime.fromisoformat(row['before']['as_of']), datetime.fromisoformat(row['after']['as_of']))


def protocol(repo, retained):
    cash, zero = Decimal('100000'), Decimal(0)
    anchor = next(row for row in retained['decisions'] if row['orders'])
    interval = interval_of(anchor)
    order = anchor['orders'][0]
    quantity, price = order['quantity'], Decimal(order['price'])
    reserved = cash - Decimal(anchor['after_submission']['available_cash'])
    reconcile = EquityPteReconcile(cash, 0)
    partial = EquityPteReport(0, 1, price, interval.start+timedelta(minutes=1), 'FILLED_PART')
    complete = EquityPteReport(0, quantity, price, interval.start+timedelta(minutes=2), 'FILLED_ALL')
    cases = [EquityPteScenario('entry-partial-duplicate-restart',
        (reconcile, EquityPteDecision(interval, interval.start), partial, partial, EquityPteRestart(), complete),
        Decimal(anchor['after']['cash']), quantity, zero)]
    for name, outcome, at in [('REJECTED','REJECTED',interval.start),
                              ('UNKNOWN','UNKNOWN',interval.start), ('EXPIRED','ACCEPTED',interval.end)]:
        cases.append(EquityPteScenario(name.lower(),
            (reconcile, EquityPteDecision(interval, at, outcome, name)),
            cash-reserved if name == 'UNKNOWN' else cash, 0, zero))
    cases.append(EquityPteScenario('reconciliation-blocked',
        (EquityPteReconcile(cash-1,0), EquityPteDecision(interval,interval.start,expected='RECONCILIATION_BLOCKED')),
        cash,0,zero))
    paid = price + (price*Decimal('.001')).quantize(Decimal('.0001'))
    cases.append(EquityPteScenario('normal-partial-expiry',
        (reconcile, EquityPteDecision(interval,interval.start), partial,
         EquityPteReport(0,1,price,interval.end,'CANCELLED_PART'), EquityPteRestart()),
        (cash-paid).quantize(Decimal('.0001')),1,zero))
    cases.append(EquityPteScenario('normal-zero-fill-expiry',
        (reconcile, EquityPteDecision(interval,interval.start),
         EquityPteReport(0,0,zero,interval.end,'CANCELLED_ALL'), EquityPteRestart()),cash,0,zero))
    # Preserve the two earlier independent RAW accounts, including their full
    # hold/promotion/rebalance/exit paths. Reports are controlled external facts.
    for index, section in enumerate([retained]+retained['previous_scenarios']):
        steps, order_index = [reconcile], 0
        for row in section['decisions']:
            span = interval_of(row)
            steps.append(EquityPteDecision(span, span.start, expected='SUBMITTED' if row['orders'] else 'NO_ORDER'))
            for result in row['orders']:
                filled = result['fill_quantity']
                stamp = span.end-timedelta(minutes=1) if filled else span.end
                steps.append(EquityPteReport(order_index, filled, Decimal(result.get('price','0')),
                                             stamp, result['status']))
                order_index += 1
            if row['session'] == section['decisions'][0]['session'] or (row['orders'] and order_index == 1):
                steps.append(EquityPteRestart())
        final = section['decisions'][-1]['after']
        cases.append(EquityPteScenario(f'retained-real-window-{index+1}',tuple(steps),
            Decimal(final['cash']),final['actual_quantity'],Decimal(final['receivable'])))
    return EquityPteInspectionProtocol(describe_inspection_environment(repo),tuple(cases))


def main(attempt):
    output = EXP/'others'/attempt
    if output.exists():
        raise FileExistsError('Keep prior attempt evidence; choose a new attempt name')
    repo = RepositoryContext.discover(ROOT)
    candidate = load_candidate(repo,CandidateKey('S018','C9396'))
    assert candidate.content_identity.content_sha256 == CONTENT
    context, _, provenance = build_data_context(repo,candidate.definition.execution_spec)
    retained = read(PRIOR/'others/pte_verification.json')
    binding = EquityInputBinding.from_dict(read(PRIOR/'others/prepared_binding.json'))
    requests = tuple(dict.fromkeys(EquityDataRequest(p.instrument,p.source,p.query) for _,p in binding.request_bindings))
    reference = ExecutionReferenceBinding.from_dict(retained['raw_binding'])
    source = EXP/'protocols/authorization.json'
    if not source.exists():
        save(source,{'recorded_on':'2026-11-08','user_reply':'同意',
            'approved_proposal':'切回 RSCH，继续策略适配与验证。',
            'candidate':'S018-C9396','content_sha256':CONTENT,'platform_commit':'ab11bc620',
            'scope':'Use existing approved data and candidate, verify the formal technical path; no parameter search.',
            'excluded':['freeze commit','production deployment','account rebinding','qualification grant','stage-four rerun']})
    confirmation = CandidateEvidence(source.relative_to(ROOT).as_posix(),sha256(source.read_bytes()).hexdigest())
    registration = StrategyRegistry(repo.research_registry_root).get_candidate_registration(candidate.key)
    selection = record_research_decision(repo,f.ResearchDecision('c9396-current-runtime-inspection','S018',f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(registration.key,registration.content_sha256,registration.record_sha256),
        confirmation,'User approved continuing C9396 adaptation and verification on the repaired platform.'))
    old = StrategyRegistry(repo.strategy_root).get_version('S018','v1')
    from datetime import date
    target = FreezeTarget('v1',old.parent_version,'C9396当前权益目标与正式执行链路技术补验；仅构造隔离待检包',
        date.fromisoformat(str(old.selection_data_cutoff)),date.fromisoformat(str(old.forward_start)))
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('America/New_York')
    window = TimeInterval(datetime(2023,1,3,9,30,tzinfo=zone),datetime(2026,10,30,16,tzinfo=zone))
    replay = EquityInspectionReplay(f.InspectionCoordinate('MU_DEVELOPMENT','STANDARD'),binding,requests,
        window,100000.,.001,execution_reference=reference)
    pte = protocol(repo,retained)
    request = CandidateInspectionRequest(candidate.key,selection,context,ExperimentRef('S018',EXP.name),target,
        EquityInspectionProtocol('candidate-inspection-v4','ECONOMIC_V1',0.,pte),(replay,),InspectionDataKind.HISTORICAL)
    save(output/'protocol.json',request.protocol.to_dict())
    save(output/'inputs.json',{'candidate_content':CONTENT,'data_provenance':provenance,
        'binding':binding.to_dict(),'execution_reference':reference.to_dict(),
        'selection':selection.to_dict(),'target':{'version':'v1','parent':old.parent_version},
        'note':'Ordinary candidate package preview; not the exact historical-metadata-preserving upgrade package.'})
    def progress(event):
        print(event.stage, getattr(event,'message',''),flush=True)
    report = inspect_candidate(repo,request,control=InspectionControl(max_workers=2,timeout_seconds=900,on_progress=progress))
    save(output/'report.json',report.to_dict())
    save(output/'reference.json',report.reference.to_dict())
    checked = validate_inspection(ROOT,report.reference)
    assert checked == report
    save(output/'validation.json',{'status':report.status.value,'validated':True,
        'behavior':report.behavior_equivalence.status.value,'pte':report.pte_runtime.status.value,
        'reference':report.reference.to_dict(), 'production_writes':0,'freeze_commit':False})
    print(json.dumps({'status':report.status.value,'cases':[
        {'id':x.case_id,'status':x.status.value,'summary':x.summary}
        for goal in (report.behavior_equivalence,report.pte_runtime) for x in goal.cases]},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--attempt',default='attempt01')
    main(parser.parse_args().attempt)
