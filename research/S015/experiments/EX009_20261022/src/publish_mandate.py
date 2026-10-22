"""Publish the human-confirmed S015 goal revision; no research search runs."""
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zipfile

from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, assemble_delivery,
    validate_delivery, validate_experiment, update_research_intent, ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, EvaluationResources, EvidenceRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope,
)
from czsc_trader.research_tools import delivery as d
from strategy_manager import StrategyRegistry
from strategy_runtime import validate_release_package

ROOT=Path(__file__).resolve().parents[5]
EX=ExperimentRef('S015','EX009_20261022')
EROOT=EX.resolve(ROOT)


def read(p): return json.loads(p.read_bytes())


def save(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')


def main():
    repo=RepositoryContext.discover(ROOT)
    ctx=create_research_context(repo,ResearchBatchRef('S015'),resources=EvaluationResources(1,1,13))
    assert not (ROOT/'research/S015/deliveries/MANDATE/3').exists()
    old_receipt=read(ROOT/'research/S015/deliveries/MANDATE/2/receipt.json')
    predecessor=d.DeliveryReference.from_dict(old_receipt['reference'])
    assert validate_delivery(repo,predecessor,scope=d.DeliveryValidationScope.FULL).status.value=='PASS'
    old=d.DeliveryContent.from_dict(read(ROOT/'research/S015/assets/deliveries/MANDATE/2/delivery.json')['content'])
    assert type(old.payload) is d.ResearchMandate
    preserved_paths=[p for p in (ROOT/'research/S015/deliveries').rglob('*') if p.is_file()]
    preserved={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in preserved_paths}
    family_path=ROOT/'research/registrations/S015/family.json'
    before=read(family_path)
    save(EROOT/'others/previous_intent.json',before)
    version=StrategyRegistry(repo.strategy_root).get_version('S011','v1')
    assert version.release_hash=='5da4a999f28aa699ef60641bc26d34f66e124dda8236063aeeea9b18afa9e89e'
    validate_release_package(repo.strategy_root,'S011-v1')
    manifest=read(repo.strategy_root/'S011/releases/v1/release_manifest.json')
    assert manifest['package_hash']=='d6f9bd05b4214109669edd1e49cbfd89d376d4fc993e0e5a27ae3fa07d84f055'
    comparison=read(ROOT/'research/S015/experiments/EX008_20261022/others/assessment.json')
    archive_ref=EvidenceRef.from_dict(read(ROOT/'research/S015/experiments/EX008_20261022/others/account_archives.json')['S011-v1'])
    with zipfile.ZipFile(BytesIO(archive_ref.resolve(ROOT).read_bytes())) as archive:
        metrics=json.loads(archive.read('metrics.json'))['strategy']['metrics']
        account_manifest=json.loads(archive.read('manifest.json'))
        assert metrics==comparison['statistics']['S011-v1']['metrics']
    auth={'confirmed_date':'2026-10-22','source':'human messages in this Codex conversation',
        'user_correction_verbatim':'应该先重新拟定S015的研究目标吧',
        'approved_proposal':{'goal':'在既定交易约束下，寻找累计净收益与最大回撤同时优于修复后S011-v1、并满足原有默认标准的策略。C0031仅作为已有研究证据，不预设必须沿用其机制。',
            'common_window':'2025-02-06至2026-10-21','development_window':'2025-01-02至2026-10-21',
            'baseline':'锁定修复后S011-v1的发布哈希','scope':'更新正式阶段一约定，并据此提出后续研究方案；研究执行待新阶段授权。'},
        'user_confirmation_verbatim':'确认'}
    save(EROOT/'others/authorization.json',auth)
    refs=[]
    def publish(path,name=None):
        media='text/x-python' if path.suffix=='.py' else 'text/markdown' if path.suffix=='.md' else 'application/json'
        ref=publish_evidence(ctx,MaterialEvidenceWrite(EX,name or path.stem,path.read_bytes(),media,path.suffix[1:]))
        refs.append(ref)
        return ref
    authorization=publish(EROOT/'others/authorization.json')
    source_files=[p for p in (repo.strategy_root/'S011/releases/v1').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    source_files.extend([repo.strategy_root/'S011/versions/v1.json',repo.strategy_root/'deployments/S011-v1.json'])
    source_hashes={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in source_files}
    buffer=BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(source_files): archive.writestr(p.relative_to(ROOT).as_posix(),p.read_bytes())
    release_ref=publish_evidence(ctx,MaterialEvidenceWrite(EX,'pinned_s011_release',buffer.getvalue(),'application/zip','zip'))
    refs.extend([release_ref,archive_ref])
    gate={'schema_version':1,'kind':'RSCH_FIXED_BASELINE_COMPARISON','strategy_id':'S015',
        'authorization':authorization.to_dict(),'original_defaults_source':predecessor.to_dict(),
        'default_window':{'id':'development','start':'2025-01-02','end':'2026-10-21','sessions':434},
        'comparison_window':{'id':'s011_common','start':'2025-02-06','end':'2026-10-21','sessions':415},
        'account_initialization':{'initial_cash':100000,'quantity':0,'independent_account_per_window':True},
        'one_way_cost':.001,'price_basis':'HFQ_RESEARCH','execution_contract':'DAILY_RANGE_V3',
        'force_end_liquidation':False,'baseline_reference':{'release_id':'S011-v1','release_hash':version.release_hash,
            'package_hash':manifest['package_hash'],'release_archive':release_ref.to_dict(),'account_archive':archive_ref.to_dict(),
            'release_files_sha256':source_hashes,'execution_fingerprint':comparison['common_execution_fingerprint']},
        'conditions':[{'metric':'cumulative_net_return','operator':'GT','baseline_value':metrics['return'],
            'formula':'final_equity / initial_cash - 1'},
            {'metric':'maximum_drawdown_magnitude','operator':'LT','baseline_value':abs(metrics['max_drawdown']),
             'formula':'max(1 - equity / cumulative_max_including_initial_cash)'}],
        'gate_aggregation':'ALL','comparison_uses_unrounded_values':True,'equality_passes':False,
        'overall_acceptance':'development_defaults_PASS AND s011_common_comparison_PASS',
        'unknown_or_incomparable':'NOT_PROVEN; cannot claim acceptance',
        'scope':'center only, standard cost, whole common window; no new annual, perturbation or stress dominance gate',
        'implementation_note':'RSCH computes this explicit separate-window gate; unchanged default PerformanceRequirement alone is insufficient.',
        'current_stage':'MANDATE_COMPLETE_NEXT_RESEARCH_PROPOSED_ONLY'}
    assert gate['conditions'][0]['baseline_value']==0.9158029150000013
    assert gate['conditions'][1]['baseline_value']==0.07248663749114126
    save(EROOT/'protocols/comparative_gate.json',gate)
    gate_ref=publish(EROOT/'protocols/comparative_gate.json')
    confirmation=d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED,authorization)
    new_items=(
        d.MandateItem('dual-superiority-objective',d.MandateItemKind.OBJECTIVE,
            '415日共同窗口内，中心累计净收益严格高于固定S011-v1、最大回撤幅度严格低于固定S011-v1；同时满足原434日开发池全部默认标准。精确窗口、原始数值和基线哈希绑定comparative_gate证据；不由原默认目标集合自动代算。',confirmation),
        d.MandateItem('fixed-s011-baseline',d.MandateItemKind.CONSTRAINT,
            f'S011-v1固定release_hash={version.release_hash}、package_hash={manifest["package_hash"]}；原始源码和账户归档固定，将来同名版本更新不自动替换。',confirmation),
        d.MandateItem('separate-comparison-window',d.MandateItemKind.HORIZON,
            '共同窗口2025-02-06至2026-10-21，415日，另起10万元空仓账户。原开发池2025-01-02至2026-10-21及75日预热不变；不得把继承持仓的切片冒充独立比较。',confirmation),
        d.MandateItem('mechanism-freedom',d.MandateItemKind.OBJECTIVE,
            '不限定沿用C0031或S011机制；获准研究阶段内可重新选择既有许可数据中的信息、入退出场信号和仓位逻辑，固定执行约束不自动改变。',confirmation),
        d.MandateItem('baseline-access-and-exposure',d.MandateItemKind.DATA_PERMISSION,
            '可引用已获准S011基线实现、定义及账户证据；不自动将S011的沪深300/SPX输入纳入S015新候选，新增来源另批。所有重叠历史均已见，不作为新的独立验证。',confirmation),
        d.MandateItem('current-authorization',d.MandateItemKind.RESOURCE,
            '本次确认仅完成新目标约定与后续研究方案；新的阶段二执行待批准，原C0031选型与技术检验保留为历史、不继续等待该候选冻结；冻结与PTE另批。',confirmation),
    )
    payload=d.ResearchMandate((*old.payload.items,*new_items))
    assert payload.items[:len(old.payload.items)]==old.payload.items
    save(EROOT/'others/mandate.json',payload.to_dict())
    for path in [EROOT/'others/previous_intent.json',EROOT/'others/mandate.json',
                 EROOT/'protocols/next_stage_proposal.md',Path(__file__)]:publish(path)
    report=(EROOT/'report.md').read_text(encoding='utf-8')
    report_ref=publish_evidence(ctx,ExperimentReportWrite(EX,sha256((EROOT/'report.md').read_bytes()).hexdigest(),
        ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    all_refs=tuple(dict.fromkeys((*old.evidence,*refs,report_ref)))
    receipt=assemble_delivery(repo,d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.MANDATE,3,(predecessor,)),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report.replace('](protocols/',
            '](../../../experiments/EX009_20261022/protocols/'),evidence=all_refs))
    validation=validate_delivery(repo,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS'
    intent={'research_symbol':'159326.SZ','current_phase':'阶段一目标已修订；MANDATE/3完成，新的阶段二方案待批准',
        'objective':'在固定共同窗口同时严格优于修复后S011-v1的累计净收益和最大回撤，并满足原开发池默认标准',
        'mandate':receipt.reference.to_dict(),'comparative_contract':gate_ref.to_dict(),
        'development_window':gate['default_window'],'comparison_window':gate['comparison_window'],
        'baseline':{'release_id':'S011-v1','release_hash':version.release_hash,'package_hash':manifest['package_hash']},
        'selected_candidate':None,'historical_candidate':'C0031；已有研究及技术证据保留，在新比较门下回撤不通过',
        'data_boundary':'保留原获准ETF数据及S011固定基线引用；不扩大新候选输入或封存样本范围',
        'next_gate':'用户批准新的阶段二方案后开展组件研究；阶段三、选型、冻结及PTE另行确认',
        'proposal_path':'research/S015/experiments/EX009_20261022/protocols/next_stage_proposal.md'}
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='用户确认重订S015目标，发布MANDATE/3；替换过时的C0031待冻结当前状态，保留全部历史证据。')
    assert read(family_path)['research_intent']==intent
    assert all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in preserved.items())
    assert all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in source_hashes.items())
    experiment=validate_experiment(repo,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION))
    assert experiment.status.value=='PASS'
    save(EROOT/'others/validation.json',{'delivery':receipt.reference.to_dict(),'full':validation.to_dict(),
        'experiment':experiment.to_dict(),'old_delivery_files_unchanged':len(preserved),
        'baseline_release_files_unchanged':True,'default_items_exactly_inherited':True,
        'research_execution_started':False,'current_intent':intent})
    print('MANDATE_3_FULL_PASS',receipt.reference.to_dict(),flush=True)


if __name__=='__main__':main()
