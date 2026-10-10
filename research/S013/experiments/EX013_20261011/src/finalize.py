"""Record the final report-helper repair without changing any economic evidence."""
from dataclasses import replace
import subprocess
from czsc_trader.application import publish_evidence,assemble_delivery,validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from common import ROOT,SRC,RUNS,PROTOCOLS,EXPERIMENT,read,write,context,file_hash

def main():
    before=(SRC.parent/'others/report.md').read_bytes()
    economic_hashes={name:file_hash(RUNS/name) for name in ('analysis.json','interaction.json','helper_provenance.json','account_references.json','matrix.json')}
    subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(SRC/'write_report.py')],cwd=ROOT,check=True,capture_output=True)
    assert before==(SRC.parent/'others/report.md').read_bytes()
    assert all(file_hash(RUNS/name)==digest for name,digest in economic_hashes.items())
    check=subprocess.run([str(ROOT/'.venv/Scripts/ruff.exe'),'check',str(SRC),'--output-format','concise'],cwd=ROOT,check=True,capture_output=True,text=True)
    correction={'status':'PASS','reason':'An unused report-helper plan variable referenced an import removed during lint cleanup; its source was captured before the final cleanup. Removed the unused read. No strategy source, account, metric, identity, qualification or allocation changed.',
        'report_regeneration':'EXACT_EQUAL bytes','economic_hashes_unchanged':economic_hashes,
        'final_ruff':check.stdout.strip(),'account_replays':0,
        'old_reproduction_sha256':file_hash(RUNS/'reproduction.json'),
        'original_report_helper_sha256':read(RUNS/'reproduction.json')['files']['write_report.py']['sha256'],
        'final_report_helper_sha256':file_hash(SRC/'write_report.py')}
    write(RUNS/'report_helper_correction.json',correction)
    current={'status':'FINAL_SOURCE_SNAPSHOT','original_reproduction_sha256':file_hash(RUNS/'reproduction.json'),
        'files':{p.relative_to(SRC).as_posix():{'sha256':file_hash(p),'source':p.read_text(encoding='utf-8')} for p in SRC.rglob('*.py')},
        'final_ruff':check.stdout.strip(),'report_generation_verified':'EXACT_EQUAL original report bytes',
        'counts':read(RUNS/'reproduction.json')['counts']}
    write(RUNS/'reproduction_r1.json',current)
    ctx=context(1)
    refs=[]
    for name in ('report_helper_correction.json','reproduction_r1.json'):
        refs.append(publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'ablation-final-'+name[:-5].replace('_','-'),
            (RUNS/name).read_bytes(),'application/json','json')))
    original=d.DeliveryReference.from_dict(read(PROTOCOLS/'delivery_reference.json'))
    assert original.revision==8
    document=read(ROOT/'research/S013/assets/deliveries/CANDIDATES/8/delivery.json')
    content=d.DeliveryContent.from_dict(document['content'])
    report=content.report.replace('CANDIDATES/8','CANDIDATES/9')
    report+='\n## 报告生成源码技术修订\n\n'
    report+='交付八的重现快照在最终静态检查收尾前保存了报告生成脚本中的一处多余变量读取。删除后静态检查通过，报告重新生成的字节与原稿精确相同；策略源码、全部账户、指标和资格均未改变，没有重放账户。原交付八及原快照保留，交付九显式关联修复说明与最终可重现源码。\n\n'
    for ref in refs:
        report+=f'- [{ref.name}](../../../assets/deliveries/CANDIDATES/9/{ref.path})\n'
    mandate=d.DeliveryReference.from_dict(read(PROTOCOLS/'plan.json')['mandate'])
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,9,(mandate,original)),
        replace(content,report=report,evidence=content.evidence+tuple(refs)))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS,validation.to_dict()
    write(PROTOCOLS/'delivery_reference_v8.json',original.to_dict())
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation_r1.json',{'status':'PASS','reference':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'report_correction':correction,'new_candidate_registrations':0,'new_qualified_configurations':0})
    print({'final_delivery':receipt.reference.to_dict(),'full_validation':'PASS','report_regeneration':'EXACT_EQUAL','economic_hashes':'UNCHANGED'},flush=True)

if __name__=='__main__':
    main()
