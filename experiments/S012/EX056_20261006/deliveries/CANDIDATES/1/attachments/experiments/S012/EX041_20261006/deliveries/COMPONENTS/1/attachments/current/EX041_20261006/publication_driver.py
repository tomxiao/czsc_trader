from dataclasses import asdict
from pathlib import Path
import importlib,json,sys,types,subprocess
from czsc_trader.application import RepositoryContext,assemble_delivery,validate_delivery,validate_archives,update_research_intent
from czsc_trader.experiment_archive import build_experiment_manifest
from czsc_trader.research_tools import DeliveryValidationScope
from research_experiment import load_experiment
ROOT=Path.cwd();EXP=ROOT/'experiments/S012/EX041_20261006';MAT=ROOT/'research/S012/materials'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
def main():
    assert read(EXP/'artifacts/verification/independent.json')['status']=='PASS'
    repo=RepositoryContext.discover(ROOT);pkg=types.ModuleType('s012_native_publication');pkg.__path__=[str(EXP)];sys.modules[pkg.__name__]=pkg
    delivery=importlib.import_module(pkg.__name__+'.delivery').NativeScopeDelivery(ROOT)
    c=delivery.build();print('CONTENT',len(c.payload.components),len(c.facts),c.status.value,flush=True)
    receipt=assemble_delivery(repo,delivery);write(MAT/'stage2_native_components_reference_20261006.json',receipt.reference.to_dict())
    full=validate_delivery(repo,receipt.reference);write(MAT/'stage2_native_components_validation_20261006.json',full.to_dict())
    print('FULL',full.status.value,flush=True)
    if full.status.value!='PASS':raise ValueError('delivery validation failed')
    loaded=load_experiment(EXP)
    build_experiment_manifest(EXP,{'experiment_id':EXP.name,'strategy_id':'S012','symbol':'518850.SH','development_cutoff':'2026-09-30',
        'outcome':'INCONCLUSIVE','purpose':'阶段二原生有效域和机会日历贡献归因，完整继承与反证交付',
        'platform_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'definition_sha256':loaded.definition.sha256,'source_sha256':loaded.binding.source_sha256,'delivery':receipt.reference.to_dict()})
    check=validate_archives(repo,archive=EXP);write(MAT/'stage2_native_archive_validation_20261006.json',asdict(check))
    print('ARCHIVE',check.status,flush=True)
    if check.status!='PASS':raise ValueError('archive validation failed')
    integrity=validate_delivery(repo,receipt.reference,scope=DeliveryValidationScope.INTEGRITY)
    write(MAT/'stage2_native_sealed_integrity_20261006.json',integrity.to_dict())
    if integrity.status.value!='PASS':raise ValueError('sealed integrity failed')
    intent=read(ROOT/'research/registrations/S012/family.json')['research_intent']
    if EXP.name not in intent['experiments']:intent['experiments'].append(EXP.name)
    intent.update(stage='COMPONENTS',status='COMPLETE',delivery=receipt.reference.to_dict(),
        research_summary='阶段二147条完整记录；5推荐职责：O01/M05两机会、C01/C02/C03三风险。原生与共同域归因完成，Q07降为可选确认候选，纯动量潜在净负，互补去2025/费用反证保持；216路径1512年度6624相位、独立49728字段PASS；完整账户目标未复验。',
        next_stage='建议获批后做O01有无Q07、M05独立/联合、纯动量及其加机会的完整账户对照；阶段三须用户决定',
        pending=['全部已见开发池、真实历史发布时点及源代理限制保持','原三个完整账户目标未复验','新源/依赖、平台、生产及远端操作另批准'])
    p=ROOT/'.tmp/s012-native-scope-20261006/final_intent.json';write(p,{'research_state':'RESEARCHING','research_intent':intent})
    result=update_research_intent(repo,'S012',p,actor='RSCH',reason='用户阶段二收益组件目标完成，完整继承交付及原生域/确认反证，等待后续指示')
    write(MAT/'stage2_native_result_20261006.json',asdict(result))
    print('COMPLETE',receipt.reference.content_sha256,flush=True)
if __name__=='__main__':main()
