"""Immutable report-only corrections; no data/model/account/quota execution."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef

OLD='父OFF完整history和原C8880真实decisions全部字段精确相等；独立ON重建完整策略状态和决策。'
NEW='本轮是新的学习策略，原C8880只作经济及执行对照，没有进行父OFF等价核验。新策略自身的预测、完整策略状态、真实决策及会计账本已独立核验。'

def correct(number):
    c=g.base.common()
    ctx=c.context(1)
    exp=ExperimentRef('S013',f'EX{number:03d}_20261012')
    path=ROOT/'research/S013/experiments'/exp.experiment_id
    original=path/'others/report.md'
    old=original.read_text('utf-8')
    assert old.count(OLD)==1
    audit_refs=g.read(path/'protocols/audit_references.json')
    verification=EvidenceRef.from_dict(audit_refs['verification.json'])
    report=old.replace(OLD,NEW)
    report+='\n\n## 报告文字勘误（v2）\n\n原版身份核验段沿用了不适用于本轮的父OFF等价表述；本版明确删除该项未经执行的核验声明。新策略实际独立信号、订单和连续账本PASS，所有经济数值与失败结论保持原证据；未重跑数据、拟合或账户，额度不变。原版及其SHA证明保留，最终阅读以本修订版为准。\n'
    correction={'status':'REPORT_ONLY_CORRECTION','original_report':original.relative_to(ROOT).as_posix(),
        'original_sha256':g.digest(original),'invalid_statement':OLD,'correct_statement':NEW,
        'verification':verification.to_dict(),'economic_values_changed':False,'new_accounts':0,
        'new_experiments':0,'quota_delta':0,'source':Path(__file__).relative_to(ROOT).as_posix()}
    work=ROOT/'.tmp/s013-new-goal/report_corrections'/exp.experiment_id
    work.mkdir(parents=True,exist_ok=True)
    g.write(work/'correction.json',correction)
    ref=g.put(ctx,exp,work/'correction.json')
    source=g.put(ctx,exp,Path(__file__))
    evidence=(verification,EvidenceRef.from_dict(ref),EvidenceRef.from_dict(source))
    summary=m.SearchSummary(exp.experiment_id+'-report-v2','只修正报告未经执行的OFF核验声明',
        '引用原实际中心及独立审计，不新读取数据、不拟合、不运行账户',0,0,
        '新策略自身完整预测和账本已核验；C8880 OFF等价未执行；经济失败结论不变',
        ('只修正文案，新增实验和账户均0，额度不变','原版报告保持不可变，修订版显式关联原SHA'),evidence)
    revision=max(int(p.name) for p in (ROOT/'research/S013/deliveries/CANDIDATES').iterdir() if p.name.isdigit())+1
    predecessor=m.DeliveryReference.from_dict(g.read(ROOT/'research/S013/assets/deliveries/MANDATE/7/receipt.json')['reference'])
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.CANDIDATES,revision,(predecessor,)),
        m.DeliveryContent(m.CandidateSet((),(),(summary,),'修正报告核验声明，实际经济失败结论保持原证据'),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validated=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    assert validated.status.value=='PASS'
    formal=ROOT/f'research/S013/deliveries/CANDIDATES/{revision}/report.md'
    copy=path/'others/report_v2.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert copy.read_bytes()==formal.read_bytes()
    proof={'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),'experiment_report':copy.relative_to(ROOT).as_posix(),
        'formal_sha256':g.digest(formal),'copy_sha256':g.digest(copy),'formal_bytes':formal.stat().st_size,
        'copy_bytes':copy.stat().st_size,'exact_bytes':True,'supersedes_report_statement_only':correction}
    g.write(path/'protocols/report_copy_verification_v2.json',proof)
    g.write(path/'protocols/report_correction_v2.json',{'correction':ref,'source':source,
        'delivery_reference':receipt.reference.to_dict(),'validation':validated.to_dict(),'final_report':proof['experiment_report']})
    source_copy=path/'src/report_correction_v2.py'
    with source_copy.open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print({'experiment':exp.experiment_id,'CANDIDATES':revision,'FULL':'PASS','report_v2_copy':'EXACT','quota_delta':0,'new_accounts':0},flush=True)

if __name__=='__main__':
    legacy=ROOT/'.tmp/s013-new-goal/native_failure_closeout.py'
    content=legacy.read_text('utf-8')
    assert content.count(OLD)==1
    with (legacy.parent/'native_failure_closeout_v2.py').open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(content.replace(OLD,NEW))
    for number in (96,97):
        correct(number)
