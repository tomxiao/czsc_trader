"""RSCH same-version upgrades: retained signals, exact packages, isolated formal PTE."""
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, register_candidate, CandidateRegistrationRequest, load_candidate,
    publish_evidence, FrozenRuntimeUpgradeRequest, prepare_frozen_runtime_upgrade,
    apply_frozen_runtime_upgrade, EquityInspectionReplay)
from czsc_trader.application.equity_inspection import replay_account
from czsc_trader.application.runtime_migration import PreparedFrozenRuntimeUpgrade
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef,
    MaterialEvidenceWrite, EquityEvaluationRequest, EvaluationBenchmark, EquityBuyHold,
    ResearchExecutionSession, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)
from czsc_trader.application import validate_experiment
from dataflows import (ProviderConfig, EquityDataRequest, EquityQuery, EquityProduct,
    PriceAdjustment, TimeInterval, PreparePolicy)
from strategy_manager import CandidateKey, StrategyRegistry, canonical_sha256
from strategy_manager.freeze_contracts import FrozenVersionReference, ResearchEvidenceOwner, ResearchEvidenceRef, InspectionCoordinate
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, InspectionRuntimePermit
from strategy_runtime.equity_definition import execution_spec_from_dict
from strategy_runtime.deployment import validate_release_integrity, validate_release_package
from strategy_runtime.inspection import collect_inspection_environment
from paper_trading_engine.execution_reference import ExecutionReferenceBinding
from paper_trading_engine.equity_inspection import (inspect_equity_release, verify_equity_inspection_facts,
    EquityPteInspectionProtocol, EquityPteScenario, EquityPteDecision, EquityPteReport,
    EquityPteReconcile, EquityPteRestart)

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
ZONE = ZoneInfo('Asia/Shanghai')
sys.dont_write_bytecode = True
CHOICES = {'S001-v1':'C9990', 'S001-v2':'C9991', 'S007-v1':'C9991',
           'S011-v1':'C9990', 'S015-v1':'C9990'}


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def module(family, name):
    home = ROOT / 'research' / family / 'materials/current_contract_upgrade_20261108'
    sys.path.insert(0, str(home))
    spec = importlib.util.spec_from_file_location(f'{family}_{name}', home / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def stamp(day, hour, minute=0):
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), ZONE).replace(hour=hour, minute=minute)


def material(context, exp, name, value):
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) + '\n').encode()
    return publish_evidence(context, MaterialEvidenceWrite(exp, name, content, 'application/json', 'json'))


def research_ref(ref):
    return ResearchEvidenceRef(ResearchEvidenceOwner(ref.experiment.strategy_id, ref.experiment.experiment_id),
                               ref.evidence_id, ref.sha256)


def package_candidate(context, candidate, prepared):
    stage = prepared.plan_path.parent / 'staged'
    verified = validate_release_package(stage, prepared.original.strategy_id + '-' + prepared.original.version)
    packed = EquityStrategyCandidate(candidate.strategy_id, candidate.candidate_id,
        EquityStrategyDefinition.from_dict(dict(verified.release.payload['equity_definition'])), verified.source_root)
    assert packed.content_identity == candidate.content_identity
    return packed


def isolated(prepared, candidate, label, protocol_hash):
    run_id = 'upgrade-' + prepared.original.strategy_id + '-' + label + '-' + uuid4().hex[:10]
    work = ROOT / '.tmp/strategy-inspection' / run_id
    repository = work / 'repository'
    shutil.copytree(prepared.plan_path.parent / 'staged', repository / 'strategies')
    shutil.copy2(ROOT/'strategies'/candidate.strategy_id/'family.json',
                 repository/'strategies'/candidate.strategy_id/'family.json')
    verified = validate_release_package(repository / 'strategies', prepared.original.strategy_id + '-' + prepared.original.version)
    permit = InspectionRuntimePermit(run_id, verified.release.release_id, verified.release.release_hash,
        verified.package_sha256, protocol_hash, repository, work)
    packed = replace(candidate, source_root=verified.source_root)
    assert packed.content_identity == candidate.content_identity
    return permit, packed


def inspect_pte(prepared, candidate, context, replay, facts, output, fee):
    buy = next(o for o in facts['orders'] if o['side'] == 'BUY')
    interval = TimeInterval(datetime.fromisoformat(buy['valid_start']), datetime.fromisoformat(buy['valid_end']))
    initial, zero = Decimal('100000'), Decimal(0)
    environment = collect_inspection_environment(ROOT)
    probe = EquityPteInspectionProtocol(environment, (EquityPteScenario('quote-probe',
        (EquityPteReconcile(initial,0), EquityPteDecision(interval,interval.start,'REJECTED','REJECTED')),
        initial,0,zero),))
    permit, packed = isolated(prepared,candidate,'probe',canonical_sha256(probe.to_dict()))
    probed = inspect_equity_release(candidate=packed,dataflows=context.data,binding=replay.input_binding,
        requests=replay.requests,execution_reference=replay.execution_reference,initial_cash=float(initial),
        fee_rate=fee,permit=permit,protocol=probe)
    save(output/'pte-probe.json',probed)
    case = probed['scenarios'][0]
    assert case['status'] == 'PASS', case['summary']
    intent = next(i for i in case['facts']['intents'] if i['side']=='BUY')
    quantity = int(intent['quantity'])
    price = Decimal(str(intent['limit_price']))
    assert quantity >= 200
    def money(x):
        return x.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
    cost = money(Decimal(100)*price*Decimal(str(fee))) + money(Decimal(quantity-100)*price*Decimal(str(fee)))
    final_cash = initial - quantity*price - cost
    reserve = money(quantity*price*(1+Decimal(str(fee))))
    reconcile = EquityPteReconcile(initial,0)
    partial = EquityPteReport(0,100,price,interval.start+timedelta(minutes=1),'FILLED_PART')
    complete = EquityPteReport(0,quantity,price,interval.start+timedelta(minutes=2),'FILLED_ALL')
    scenarios = [EquityPteScenario('partial-duplicate-complete-restart',
        (reconcile,EquityPteDecision(interval,interval.start),partial,partial,complete,EquityPteRestart()),
        final_cash,quantity,zero)]
    for name,outcome,at in [('REJECTED','REJECTED',interval.start),('UNKNOWN','UNKNOWN',interval.start),
                            ('EXPIRED','ACCEPTED',interval.end)]:
        scenarios.append(EquityPteScenario(name.lower(),(reconcile,EquityPteDecision(interval,at,outcome,name)),
            initial-reserve if name=='UNKNOWN' else initial,0,zero))
    scenarios.append(EquityPteScenario('reconciliation-blocked',
        (EquityPteReconcile(initial-1,0),EquityPteDecision(interval,interval.start,expected='RECONCILIATION_BLOCKED')),
        initial,0,zero))
    scenarios.append(EquityPteScenario('normal-partial-expiry',
        (reconcile,EquityPteDecision(interval,interval.start),partial,
         EquityPteReport(0,100,price,interval.end,'CANCELLED_PART'),EquityPteRestart()),
        initial-100*price-money(100*price*Decimal(str(fee))),100,zero))
    protocol = EquityPteInspectionProtocol(environment,tuple(scenarios))
    permit, packed = isolated(prepared,candidate,'verify',canonical_sha256(protocol.to_dict()))
    outcome = inspect_equity_release(candidate=packed,dataflows=context.data,binding=replay.input_binding,
        requests=replay.requests,execution_reference=replay.execution_reference,initial_cash=float(initial),
        fee_rate=fee,permit=permit,protocol=protocol)
    save(output/'pte-protocol.json',protocol.to_dict())
    save(output/'pte.json',outcome)
    assert outcome['status']=='PASS', [(x['case_id'],x['status'],x['summary']) for x in outcome['scenarios']]
    verify_equity_inspection_facts(outcome,protocol.to_dict())
    return outcome


def main(reference, phase):
    family,version = reference.split('-')
    repo = RepositoryContext.discover(ROOT)
    state_path = HERE / (reference+'.json')
    if not state_path.exists():
        old = validate_release_integrity(repo.strategy_root,reference)
        spec = execution_spec_from_dict(dict(old.release.payload['equity_definition']['execution_spec']))
        context = create_research_context(repo,ResearchBatchRef(family),
            providers=ProviderConfig(bindings={},equity_bindings={}),execution_spec=spec)
        draft_path = HERE / (reference+'-draft.json')
        if draft_path.exists():
            exp = ExperimentRef.from_dict(read(draft_path))
        elif reference == 'S007-v1' and (ROOT/'research/S007/experiments/EX008_20261108').is_dir():
            exp = ExperimentRef('S007','EX008_20261108')
        else:
            exp = create_experiment(context,ExperimentRequest('已部署冻结策略当前合同适配',
                '保留金融信号和报价规则，将资金与数量交给EC后是否通过当前回放和隔离PTE？',date(2026,11,8)))
        save(draft_path, exp.to_dict())
        built = module(family,'adaptation').build(version,CHOICES[reference],
            ROOT/'.tmp/deployed-contract-upgrade/build'/uuid4().hex)
        destination = exp.resolve(ROOT)/'src'/CHOICES[reference]/'strategy_runtime'
        if destination.exists():
            for p in built.source_root.iterdir():
                assert (destination/p.name).read_bytes() == p.read_bytes()
        else:
            shutil.copytree(built.source_root, destination)
        candidate = replace(built, source_root=destination)
        signal = read(ROOT/f'research/{family}/materials/current_contract_upgrade_20261108/verification.json')
        assert signal['status']=='PASS'
        auth = material(context,exp,'upgrade-authorization',{
            'instruction':'其他几个已部署PTE的策略，都要完成升级',
            'exclusions':['S003-v1：用户要求暂不升级','S002-v1：用户要求无需升级'],
            'reference':reference,'candidate':candidate.candidate_id,'content':candidate.content_identity.content_sha256,
            'scope':'同版本本地冻结适配；报价规则/金融条件保持，采用当前账户权益目标；不写prod或授予资格'})
        signal_ref = material(context,exp,'financial-signal-verification',signal)
        registration=register_candidate(repo,CandidateRegistrationRequest(candidate,exp,(),candidate.definition.dependencies))
        state={'reference':reference,'experiment':exp.to_dict(),'candidate':candidate.key.to_dict(),
            'content':registration.content_sha256,'original':FrozenVersionReference(family,version,
                old.release.release_hash,old.package_sha256).to_dict(),
            'authorization':auth.to_dict(),'signal_evidence':signal_ref.to_dict()}
        save(state_path,state)
    state=read(state_path)
    exp=ExperimentRef.from_dict(state['experiment'])
    home=exp.resolve(ROOT)
    candidate=load_candidate(repo,CandidateKey(**state['candidate']))
    assert candidate.content_identity.content_sha256==state['content']
    original=FrozenVersionReference.from_dict(state['original'])
    if phase=='verify':
        output=home/'others'/('attempt-'+uuid4().hex[:10])
        output.mkdir(parents=True)
        context,sources,provenance=module(family,'data_context').build_data_context(candidate)
        history_start=date(2026,8,1) if family in ('S001','S007') else date(2024,9,9) if family=='S015' else date(2024,12,26)
        end='2026-11-04' if family in ('S001','S007') else '2026-10-20'
        window=TimeInterval(stamp('2026-09-01',9,30),stamp(end,15))
        policy=candidate.definition.execution_policy.settings
        fee=float(policy.get('capital',{}).get('fee_rate',.001))
        request=EquityEvaluationRequest(exp,candidate,window,history_start,sources,100000.,fee,
            benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),
            drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE')
        with ResearchExecutionSession(context,experiment=exp) as session:
            ready=context.evaluation.prepare(request,execution=session)
        raw=EquityDataRequest(candidate.instrument,sources.bars,EquityQuery(EquityProduct.BARS,
            history_start,date.fromisoformat(end),candidate.definition.execution_spec.decision_clock,PriceAdjustment.NONE))
        raw_ready=context.data.prepare((raw,),policy=PreparePolicy.REUSE)
        assert raw_ready.ready, str(raw_ready.items)
        fetched=context.data.fetch(raw,prepared=raw_ready.reference)
        assert fetched.ready
        execution_ref=ExecutionReferenceBinding(raw.parameters,raw_ready.reference,fetched.identity.content_sha256)
        replay=EquityInspectionReplay(InspectionCoordinate('migration','standard'),ready.request.input_binding,
            ready.request.requests(context.execution_spec),window,100000.,fee,execution_reference=execution_ref)
        save(output/'input.json',{'binding':replay.input_binding.to_dict(),'raw':execution_ref.to_dict(),'provenance':provenance})
        before=replay_account(candidate,context.data,replay)
        auth=research_ref(EvidenceRef.from_dict(state['authorization']))
        signal_ref=research_ref(EvidenceRef.from_dict(state['signal_evidence']))
        pending=prepare_frozen_runtime_upgrade(repo,FrozenRuntimeUpgradeRequest(original,candidate,auth,
            '保留金融信号及报价规则，策略输出当前账户权益目标，EC负责资金数量与执行；原状态锁迁出。',
            'RSCH',(signal_ref,),ROOT/'.tmp/deployed-contract-upgrade'/reference/output.name/'review'))
        packed=package_candidate(repo,candidate,pending)
        after=replay_account(packed,context.data,replay)
        assert before==after,'candidate/package replay differs'
        save(output/'candidate-replay.json',before)
        pte=inspect_pte(pending,candidate,context,replay,before['facts'],output,fee)
        summary={'status':'PASS','reference':reference,'candidate':candidate.key.to_dict(),'content':state['content'],
            'candidate_package_exact':True,'counts':{k:len(v) for k,v in before['facts'].items()},
            'window':{'start':window.start.isoformat(),'end':window.end.isoformat()},'history_start':history_start.isoformat(),
            'fee_rate':fee,'pte_status':pte['status'],'pte_scenarios':len(pte['scenarios']),
            'pte_coverage':pte['coverage'],'original':state['original'],'migrated':pending.migrated.to_dict(),
            'limits':['No economic equivalence of old entry-cash lock and current-equity rebalancing.',
                      'Migration technical window, not new research selection or phase-four validation.',
                      'Recorded isolated broker, no live order or prod change.'],
            'files':{p.name:sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}}
        refs=[]
        for p in output.iterdir():
            if p.is_file():
                refs.append(publish_evidence(context,MaterialEvidenceWrite(exp,'upgrade-'+p.stem,p.read_bytes(),'application/json','json')))
        summary_ref=material(context,exp,'upgrade-technical-summary',summary)
        final=prepare_frozen_runtime_upgrade(repo,FrozenRuntimeUpgradeRequest(original,candidate,auth,
            '保持版本号及历史来源；HFQ策略输出当前账户权益目标，原金融信号和报价规则保持，执行交EC。',
            'RSCH',(signal_ref,research_ref(summary_ref),*(research_ref(r) for r in refs)),
            ROOT/'.tmp/deployed-contract-upgrade'/reference/output.name/'final'))
        assert final.migrated==pending.migrated
        state.update(verification=summary,verification_ref=summary_ref.to_dict(),
            output=output.relative_to(ROOT).as_posix(),prepared={'plan_path':final.plan_path.relative_to(ROOT).as_posix(),
                'plan_sha256':final.plan_sha256,'original':final.original.to_dict(),'migrated':final.migrated.to_dict()})
        save(state_path,state)
        print(json.dumps({'reference':reference,**summary},ensure_ascii=False),flush=True)
        return
    p=state['prepared']
    prepared=PreparedFrozenRuntimeUpgrade(ROOT/p['plan_path'],p['plan_sha256'],
        FrozenVersionReference.from_dict(p['original']),FrozenVersionReference.from_dict(p['migrated']))
    receipt=apply_frozen_runtime_upgrade(repo,prepared)
    assert apply_frozen_runtime_upgrade(repo,prepared)==receipt
    current=validate_release_package(repo.strategy_root,reference)
    assert current.package_sha256==receipt.migrated.package_hash
    packed=EquityStrategyCandidate(family,candidate.candidate_id,
        EquityStrategyDefinition.from_dict(dict(current.release.payload['equity_definition'])),current.source_root)
    assert packed.content_identity==candidate.content_identity
    archived=StrategyRegistry(receipt.archive_path/'strategies').get_version(family,version)
    installed=StrategyRegistry(repo.strategy_root).get_version(family,version)
    assert {k:v for k,v in archived.to_dict().items() if k not in ('strategy_payload','release_hash')}=={
        k:v for k,v in installed.to_dict().items() if k not in ('strategy_payload','release_hash')}
    context=create_research_context(repo,ResearchBatchRef(family),providers=ProviderConfig(bindings={},equity_bindings={}))
    result={'status':receipt.status.value,'original':receipt.original.to_dict(),'migrated':receipt.migrated.to_dict(),
        'receipt':receipt.receipt_path.relative_to(ROOT).as_posix(),'history_preserved':True,'idempotent':True,
        'qualification':StrategyRegistry(repo.strategy_root).current_qualification(family,version).value,'production_writes':0}
    result_ref=material(context,exp,'same-version-upgrade-result',result)
    summary=state['verification']
    text=f'''# {reference} 当前合同原地升级

Status: COMMITTED

按用户授权，将{reference}同版本更新为{candidate.candidate_id}，本地升级、历史归档和重复调用核验通过。原金融信号、参数及报价规则保留；策略只读取HFQ并输出当前策略账户权益目标，资金、数量、订单由EC处理。S003与S002按用户要求不升级。

金融信号验证见本实验关联的financial-signal-verification证据。新候选与实际待替换包按同一输入回放，全部事实及最终状态精确一致：{json.dumps(summary['counts'],ensure_ascii=False)}。迁移验证窗口{summary['window']['start']}至{summary['window']['end']}；本轮未重新选型或追加阶段四自检。

隔离PTE经FormalV4AdviceClient、AccountEngine、ChannelExecution和PaperStore运行{summary['pte_scenarios']}个场景，部分成交、重复回报、重启、完成、拒单、未知提交、过期、对账阻断均通过；外部成交为记录型网关事实，无真实渠道下单。

旧入场现金/数量锁与当前权益目标会产生不同的补足及再平衡，因此不宣称新旧账户收益、订单和资金完全等价。原研究及自检证据保持原口径；本次仅完成已授权合同迁移。数据来自原DFLS及已发布输入证据，详细来源、转换和时间假设见本实验技术输入材料。

新发布哈希`{receipt.migrated.release_hash}`；新包哈希`{receipt.migrated.package_hash}`。策略编号、版本号、原候选及实验来源、历史日期未变。新发布资格为{result['qualification']}；没有修改PTE prod、生产账户绑定或授予模拟交易许可。

下一步由DEV准备获批的发布和账户重绑。已完成的S018-v1保持不变。
'''
    (home/'report.md').write_text(text,encoding='utf-8')
    pub=publish_evidence(context,ExperimentReportWrite(exp,sha256((home/'report.md').read_bytes()).hexdigest(),
        ExperimentOutcome.COMPLETED,(EvidenceRef.from_dict(state['signal_evidence']),
        EvidenceRef.from_dict(state['verification_ref']),result_ref)))
    checked=validate_experiment(repo,ExperimentValidationRequest(exp,ExperimentValidationScope.REPORT_PUBLICATION))
    assert checked.status.value=='PASS',checked.issues
    state.update(result=result,result_ref=result_ref.to_dict(),report=pub.to_dict(),validation='PASS')
    save(state_path,state)
    print(json.dumps({'reference':reference,**result},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('reference',choices=tuple(CHOICES))
    parser.add_argument('phase',choices=('verify','apply'))
    args=parser.parse_args()
    main(args.reference,args.phase)
