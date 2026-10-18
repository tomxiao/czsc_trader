"""Publish scoped prerequisite evidence and update intent without stage results."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (RepositoryContext, ResearchIntentUpdate, create_research_context,
                                    publish_evidence, update_research_intent)
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef

ROOT=Path(__file__).resolve().parents[5]
OUT=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def main():
    assert not (OUT/'publication.json').exists(), 'Do not overwrite published evidence index'
    inputs=read(OUT/'others/accepted_financial_inputs.json')
    review=read(OUT/'others/review.json')
    assert inputs['status']=='READY_FOR_STAGE_TWO_PUBLIC_FINANCIAL_INFORMATION_RESEARCH_WITH_DECLARED_LIMITS'
    assert review['status']=='PASS_WITH_DECLARED_LIMITS'
    registry=ROOT/'research/registrations/S014/family.json'
    before=read(registry)
    intent=deepcopy(before['research_intent'])
    protected={key:value for key,value in intent.items() if key not in {'stage','pending'}}
    assert 'financial_input_readiness' not in intent
    repository=RepositoryContext.discover(ROOT)
    context=create_research_context(repository,ResearchBatchRef('S014'))
    refs={}
    files=[path for path in sorted(OUT.rglob('*')) if path.is_file() and path.name!='.gitignore' and '__pycache__' not in path.parts]
    for path in files:
        relative=path.relative_to(OUT).as_posix()
        suffix=path.suffix[1:]
        media={'json':'application/json','md':'text/markdown','py':'text/x-python','csv':'text/csv','pdf':'application/pdf'}[suffix]
        name='fin-ready-'+relative.replace('/','-').replace('.','-')
        if len(name)>100:
            name='fin-ready-'+sha256(relative.encode()).hexdigest()[:48]+'-'+path.stem[:20]
        ref=publish_evidence(context,MaterialEvidenceWrite(ExperimentRef('S014','EX035_20261018'),name,
            path.read_bytes(),media,suffix))
        assert ref.resolve(ROOT).read_bytes()==path.read_bytes()
        refs[relative]=ref.to_dict()
    assert read(registry)==before
    intent['stage']='财务前置准备完成：公开原文与保守时点约定下可重返阶段二，尚无新增财务机制结果'
    intent['pending']=['阶段二：先锁定F1/F2标签、对照及统计预算，再执行财务信息增量检验；本轮未生成收益标签、模型或账户。',
        '遵守已验收九字段、逐字段可用时间、25个披露日期聚类；供应商历史入库和未观察修订链仍未知。']
    intent['financial_input_readiness']={'status':inputs['status'],'evidence':refs,
        'preparation_reference':inputs['preparation_reference'],'scope':inputs['scope'],
        'new_labels':0,'new_models':0,'new_accounts':0,'original_core_fields':9,
        'main_mechanism_field_period_cells_reconciled':165,'reconciled_value_cells':296,
        'unseparated_receivable_cells':1,'strict_vendor_pit_certified':False,
        'historical_eligibility_changed':False,'fees_execution_targets':'UNCHANGED',
        'authorization':'增补财务数据的目标是希望研究能重新进入阶段二，请你自主完成进入阶段二之前的工作'}
    update_research_intent(repository,context.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成用户授权的重返阶段二前置工作：33期四表正式准备、38份官方全文、297位验收与逐字段时钟；保留供应商历史未知及应收缺项，不改变历史实验或经济目标。')
    after=read(registry)
    assert all(after['research_intent'][key]==value for key,value in protected.items())
    assert after['research_state']==before['research_state']
    result={'status':'PUBLISHED_PRE_STAGE2_FINANCIAL_READINESS','association':'Post-EX035 prerequisite facts; no new experiment, stage result or candidate',
        'evidence':refs,'report_ref':refs['report.md'],'preparation_reference':inputs['preparation_reference'],
        'historical_state_preserved':True,'financial_research_can_start_under_declared_limits':True,
        'strict_vendor_pit_certified':False,'new_return_labels':0,'new_models':0,'new_accounts':0}
    with (OUT/'publication.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps({'status':result['status'],'published_files':len(refs),'new_labels_models_accounts':0}))


if __name__=='__main__':
    main()
