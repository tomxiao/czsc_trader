"""Append immutable link navigation correction; never edit original reports."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
MAT=ROOT/'research/S013/materials'
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_confirm_execution as base  # noqa: E402
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

def main():
    old=MAT/'research_pause_20261012.md'
    initial_sha=base.digest(old)
    original=old.read_text('utf-8')
    named={'暂停收尾':base.read(MAT/'research_pause_evidence_20261012.json'),
        '203中心审查':base.read(ROOT/'research/S013/reviews/20261012_new_four_203/evidence_references.json'),
        '117频率复盘':base.read(ROOT/'research/S013/reviews/20261012_frequency_117/evidence_references.json')}
    navigation='# S013证据导航（2026-10-12）\n\n链接均为项目根目录相对路径，使用EvidenceRef.repository_path；EvidenceRef.path的evidence/hash是内部逻辑路径，不能直接作为项目文件路径。历史报告和证据不覆盖，此索引提供可核对的实际资产路径。\n'
    items=[]
    for title,refs in named.items():
        navigation+='\n## '+title+'\n\n'
        for name,value in refs.items():
            ref=EvidenceRef.from_dict(value)
            assert ref.experiment.strategy_id=='S013'
            path=ref.resolve(ROOT)
            assert base.digest(path)==ref.sha256
            navigation+=f'- [{name}]({ref.repository_path})：SHA256 {ref.sha256}\n'
            items.append({'group':title,'name':name,'reference':ref.to_dict(),'repository_path':ref.repository_path})
    index=MAT/'research_evidence_index_20261012.md'
    with index.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(navigation)
    report=original
    for value in named['暂停收尾'].values():
        ref=EvidenceRef.from_dict(value)
        needle='('+ref.path+')'
        assert report.count(needle)==1
        report=report.replace(needle,'('+ref.repository_path+')')
    report+='\n\n## 证据导航修订（v2）\n\n仅将收尾报告中的内部逻辑路径改为项目根目录实际相对路径；原报告及SHA保留，经济结果、暂停决定、额度和资格均不变。[203审查及117复盘证据索引](research/S013/materials/research_evidence_index_20261012.md)提供旧报告关联证据的实际路径。此修订没有新研究计算。\n'
    correction={'kind':'REPORT_NAVIGATION_ONLY_CORRECTION','original_report':old.relative_to(ROOT).as_posix(),
        'original_sha256':initial_sha,'original_formal':base.read(MAT/'research_pause_report_copy_20261012.json')['formal'],
        'corrected_navigation':index.relative_to(ROOT).as_posix(),'links':items,'economic_values_changed':False,
        'research_status':'PAUSED','new_experiments':0,'new_accounts':0}
    record=MAT/'research_pause_navigation_correction_20261012.json'
    base.write(record,correction)
    source=MAT/'research_pause_20261012_src/navigation_v2.py'
    with source.open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    ctx=base.common().context(1)
    exp=ExperimentRef('S013','EX098_20261012')
    refs=dict(named['暂停收尾'])
    refs.update({file.name:base.put(ctx,exp,file) for file in (index,record,source)})
    evidence=tuple(EvidenceRef.from_dict(ref) for ref in refs.values())
    summary=m.SearchSummary('S013-pause-navigation-v2','暂停报告证据导航修订，原报告保留',
        '仅路径索引文档；0新评价/配置，经济状态不变',0,0,'暂停收尾报告链接修订，无新研究结论',
        ('原报告保留，不更改源证据','技术FULL是资料检查，研究目标未达成'),evidence)
    revision=max(int(p.name) for p in (ROOT/'research/S013/deliveries/CANDIDATES').iterdir() if p.name.isdigit())+1
    predecessor=m.DeliveryReference.from_dict(base.read(ROOT/'research/S013/assets/deliveries/MANDATE/7/receipt.json')['reference'])
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.CANDIDATES,revision,(predecessor,)),
        m.DeliveryContent(m.CandidateSet((),(),(summary,),'研究PAUSED，收尾导航修订完成，经济结果不变'),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS'
    base.write(MAT/'research_pause_reference_v2_20261012.json',receipt.reference.to_dict())
    base.write(MAT/'research_pause_validation_v2_20261012.json',validation.to_dict())
    base.write(MAT/'research_pause_evidence_v2_20261012.json',refs)
    formal=ROOT/f'research/S013/deliveries/CANDIDATES/{revision}/report.md'
    copy=MAT/'research_pause_20261012_v2.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert copy.read_bytes()==formal.read_bytes() and base.digest(old)==initial_sha
    base.write(MAT/'research_pause_report_copy_v2_20261012.json',{'status':'PASS','formal':formal.relative_to(ROOT).as_posix(),
        'copy':copy.relative_to(ROOT).as_posix(),'formal_sha256':base.digest(formal),'copy_sha256':base.digest(copy),
        'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,'exact_bytes':True})
    print({'research_status':'PAUSED','navigation_entries':len(items),'CANDIDATES':revision,'FULL':'PASS',
        'report_copy':'EXACT','original_report':'UNCHANGED','new_experiments':0,'new_accounts':0},flush=True)

if __name__=='__main__':
    main()
