"""Bounded public S013 stage-two declaration and immutable delivery."""
from pathlib import Path
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import sys
import shutil

from czsc_trader.application import (create_experiment, ExperimentRequest, publish_evidence,
    assemble_delivery, validate_delivery)
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK = ROOT/'.tmp/s013-stage2-20261013'
sys.path.insert(0,str(ROOT/'research/S013/experiments/EX058_20261011/src'))
import common

AUTH = {'human_message':'批准这两轮阶段二实验及上述两个数据序列的采集，请自主执行，保持现有目标和约束不变，两轮完成后暂停并给出通俗结论。',
    'recorded_date':'2026-10-13','maximum_experiments':2,'last_allowed':'EX100','pause_after_quota':True,
    'plan':'research/S013/materials/stage2_minimal_plan_20261013.md',
    'scope':'S013 only; original development pool and original14; G1 000905.SH turnover_rate_f/G2 510500.SH total_share 2019-10-09..2026-09-30,2019 warmup only',
    'goals_unchanged':True,'maximum_real_annual_fits':48,'maximum_provider_calls':16,'maximum_retries':2,
    'full_window_strategy_accounts':0,'standard32_accounts':0,'new_candidates':0,
    'no_platform_production_PTE_freeze':True}

def read(p): return json.loads(Path(p).read_text('utf-8-sig'))
def digest(p): return sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def ctx(): return common.context(1)
def public(ref):
    ref=EvidenceRef.from_dict(ref)
    if ref.experiment.strategy_id!='S013': raise ValueError('S013 only')
    return ref.resolve(ROOT)
def put(exp,p):
    p=Path(p)
    media={'.md':'text/markdown','.py':'text/x-python','.csv':'text/csv'}.get(p.suffix,'application/json')
    return publish_evidence(ctx(),MaterialEvidenceWrite(exp,'stage2-'+p.stem.replace('_','-'),p.read_bytes(),media,p.suffix[1:])).to_dict()
def ref(stage,revision):
    return d.DeliveryReference.from_dict(read(ROOT/f'research/S013/assets/deliveries/{stage}/{revision}/receipt.json')['reference'])

def allocate(number):
    if number not in (99,100): raise ValueError('Bounded two rounds')
    if number==100:
        old=ROOT/'research/S013/experiments/EX099_20261013/protocols'
        if read(old/'delivery_validation.json')['status']!='PASS' or read(old/'report_copy_verification.json')['status']!='PASS':
            raise ValueError('EX099 must close first')
    exp=create_experiment(ctx(),ExperimentRequest(
        '成交标签与两序列数据审查' if number==99 else '市场参与及份额变化的固定信息增量',
        '实际成交标签能否改善原信息机会识别？' if number==99 else '两组外部信息是否提供配对净机会增量？',date(2026,10,13)))
    if exp.experiment_id!=f'EX{number:03}_20261013': raise ValueError('Allocation mismatch; do not repeat')
    p=exp.resolve(ROOT)
    write(p/'protocols/authorization.json',AUTH)
    shutil.copyfile(ROOT/AUTH['plan'],p/'protocols/approved_plan.md')
    refs={name:put(exp,p/'protocols'/name) for name in ('authorization.json','approved_plan.md')}
    write(p/'protocols/method_references.json',refs)
    write(p/'protocols/started_budget.json',{'started':number-98,'completed':number-99,'remaining_unstarted':100-number,'authority':refs['authorization.json']})
    return exp

def mandate(exp):
    p=exp.resolve(ROOT)/'protocols'; refs=read(p/'method_references.json')
    old=read(ROOT/'research/S013/assets/deliveries/MANDATE/7/delivery.json')
    items=[x for x in d.ResearchMandate.from_dict(old['content']['payload']).items if x.item_id!='renewal_ten_rounds']
    confirmation=d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED,EvidenceRef.from_dict(refs['authorization.json']))
    items.extend([
        d.MandateItem('stage2_two_rounds_20261013',d.MandateItemKind.RESOURCE,'仅EX099–EX100两轮阶段二，至多48固定年度模型拟合；完整策略账户/32点/费用账户为0；两轮结束暂停。阶段三须另获批准。',confirmation),
        d.MandateItem('stage2_external_data_20261013',d.MandateItemKind.CONSTRAINT,'仅增加中证500指数turnover_rate_f及510500 total_share日频序列，2019-10-09..2026-09-30；2019只预热；新增序列至少一交易日滞后，历史发布修订未核实只作条件探索。保留单标的交易、原四门及固定执行合同。',confirmation)])
    report='# S013阶段二两轮恢复授权\n\n用户明确批准既定两轮与两个序列采集。经济目标、成交合同及开发池不变；旧十轮额度不续用。新增信息只用于研究，年度最终盈亏只事后验收。两轮完成暂停，不自动进入阶段三。\n'
    receipt=assemble_delivery(ctx().repository,d.DeliveryDefinition(d.ResearchBatchRef('S013'),d.DeliveryStage.MANDATE,8,(ref('MANDATE',7),)),
        d.DeliveryContent(d.ResearchMandate(tuple(items)),d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(EvidenceRef.from_dict(v) for v in refs.values())))
    validation=validate_delivery(ctx().repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    write(p/'mandate_reference.json',receipt.reference.to_dict()); write(p/'mandate_validation.json',validation.to_dict())
    if validation.status.value!='PASS': raise ValueError(validation.to_dict())

def freeze(exp,files,checks,inputs):
    p=exp.resolve(ROOT); refs=read(p/'protocols/method_references.json')
    for f in files:
        f=Path(f); name=f.relative_to(ROOT).as_posix(); refs[name]=put(exp,f)
        if f.suffix=='.py':
            dest=p/'src'/f.relative_to(WORK)
            dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(f,dest)
    manifest={'experiment':exp.to_dict(),'frozen_utc':datetime.now(timezone.utc).isoformat(),
        'method':'approved fixed H4 paired labels/ridge10/annual ECDF/zero threshold/no search',
        'sources':{Path(f).relative_to(ROOT).as_posix():digest(f) for f in files},
        'checks':checks,'input_references':inputs,'authority':refs['authorization.json'],
        'preflight_kind':'PUBLIC_COMPONENT_PRERESEARCH_CHECKS',
        'current_cli':'only backtest CLI exists; no legacy experiment preflight command invoked',
        'data_probe_sequence':'two authorized scope-only provider coverage probes precede formal allocation; no label/model calculation then; committed plan fixed before probes'}
    write(p/'protocols/preflight.json',manifest); refs['preflight.json']=put(exp,p/'protocols/preflight.json')
    write(p/'protocols/method_references.json',refs)
    for v in inputs.values(): public(v)
    return manifest

def close(exp,report,judgment,status,files,kernel,entrypoint,actual):
    p=exp.resolve(ROOT); refs=read(p/'protocols/method_references.json')
    for f in files: refs[Path(f).name]=put(exp,f)
    number=int(exp.experiment_id[2:5])
    budget={'completed':number-98,'remaining':100-number,'last_completed':exp.experiment_id,
        'pause_after_EX100':True,'objective_achieved':False,'actual':actual,'authority':refs['authorization.json']}
    write(p/'protocols/budget_receipt.json',budget); refs['budget_receipt.json']=put(exp,p/'protocols/budget_receipt.json')
    key=Path(kernel).relative_to(ROOT).as_posix()
    test=d.ComponentTestResult('STAGE2-'+str(number),exp.experiment_id,EvidenceRef.from_dict(refs['preflight.json']),status,judgment,
        tuple(EvidenceRef.from_dict(refs[Path(f).name]) for f in files))
    entry=d.ComponentEntry('EXECUTABLE-OPPORTUNITY-'+str(number),d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs[key]),entrypoint),
        '识别扣费后固定H4实际成交尝试，分离标签/信息与持仓选择影响',
        '原扣费OPEN代理L0及独立空仓固定1%成交合同L1，非连续账户',
        '固定H4；T+1买/T+5卖；无期限扫描',
        '原14及G1/G2固定主项交互，年度成熟配对训练ridge10；所有矩阵和六时钟报告',
        '原特征因果可得政策；新增信息T-1假设，历史发布及修订未核实，条件探索',
        '原510500HFQ固定锚，无现金分红叠加，1m/lot100/.001/固定1%合同',
        '已见开发池、条件性输入、单次尝试不等于完整策略或四门/32点达标',judgment,(test,))
    root=ROOT/'research/S013/deliveries/COMPONENTS'
    revisions=[int(x.name) for x in root.iterdir() if x.name.isdigit()]; rev=max(revisions)+1
    evidence=dict.fromkeys(EvidenceRef.from_dict(v) for v in refs.values())
    for v in read(p/'protocols/preflight.json')['input_references'].values(): evidence[EvidenceRef.from_dict(v)]=None
    report+='\n\n正式证据（交付包相对路径）：\n\n'+''.join(f'- [{name}]({EvidenceRef.from_dict(v).path})\n' for name,v in refs.items())
    receipt=assemble_delivery(ctx().repository,d.DeliveryDefinition(d.ResearchBatchRef('S013'),d.DeliveryStage.COMPONENTS,rev,(ref('MANDATE',8),ref('COMPONENTS',max(revisions)))),
        d.DeliveryContent(d.ComponentPanel((entry,),judgment),d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(evidence)))
    validation=validate_delivery(ctx().repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    write(p/'protocols/delivery_reference.json',receipt.reference.to_dict()); write(p/'protocols/delivery_validation.json',validation.to_dict())
    write(p/'protocols/result_references.json',refs)
    if validation.status.value!='PASS': raise ValueError(validation.to_dict())
    formal=root/str(rev)/'report.md'; copy=p/'others/report.md'
    with copy.open('xb') as f: f.write(formal.read_bytes())
    if formal.read_bytes()!=copy.read_bytes(): raise ValueError('copy differs')
    write(p/'protocols/report_copy_verification.json',{'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),
        'experiment_report':copy.relative_to(ROOT).as_posix(),'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,
        'formal_sha256':digest(formal),'copy_sha256':digest(copy),'exact_bytes':True})
    return receipt.reference

if __name__=='__main__':
    if sys.argv[1]=='allocate':
        exp=allocate(int(sys.argv[2])); print(exp.to_dict())
        if int(sys.argv[2])==99: mandate(exp)
