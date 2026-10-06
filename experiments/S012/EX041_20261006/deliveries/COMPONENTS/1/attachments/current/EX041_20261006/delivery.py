"""Complete inherited panel with native-window attribution and contrary evidence."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
from czsc_trader.research_tools import (
    ComponentEntry,ComponentPanel,ComponentTestResult,ComponentTestStatus,
    DeliveryContent,DeliveryDefinition,DeliveryReference,DeliveryStage,DeliveryStatus,
    EvidenceFile,EvidenceRef,ExperimentDefinitionRef,ExperimentEvidenceRef,
    ExperimentEvidenceUse,ExperimentOwner,Explanation,ExplanationKind,
    FactStatus,FactValue,ReproductionSpec,ResearchDeliverable,
)
EID='EX041_20261006';PRIOR='EX039_20261006'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def remap(x,paths,fids):
    if isinstance(x,list):return [remap(v,paths,fids) for v in x]
    if not isinstance(x,dict):return x
    out={k:remap(v,paths,fids) for k,v in x.items()}
    if out.get('type')=='EvidenceRef' and out['path'].startswith('attachments/'):
        out['path']=paths[out['path']]
    if 'fact_id' in out:out['fact_id']=fids[out['fact_id']]
    if 'fact_ids' in out:out['fact_ids']=[fids[v] for v in out['fact_ids']]
    return out

class NativeScopeDelivery(ResearchDeliverable[ComponentPanel]):
    def __init__(self,root):self.root=Path(root).resolve()
    @property
    def definition(self):
        prior=self.root/f'experiments/S012/{PRIOR}/deliveries/COMPONENTS/1'
        raw=read(prior/'delivery.json');rr=read(prior/'receipt.json')
        refs=[replace(ExperimentEvidenceRef.from_dict(x),use=ExperimentEvidenceUse.HISTORICAL_REFERENCE)
              for x in raw['definition']['experiments']]
        receipt=read(self.root/f'experiments/S012/{EID}/artifacts/rex/execution_receipt.json')
        refs.append(ExperimentEvidenceRef(EID,f'experiments/S012/{EID}/artifacts/rex',receipt['receipt_sha256'],ExperimentEvidenceUse.CURRENT_EVALUATION))
        return DeliveryDefinition(ExperimentOwner('S012',EID),DeliveryStage.COMPONENTS,1,
                                  predecessors=(DeliveryReference.from_dict(rr['reference']),),experiments=tuple(refs))
    def build(self):
        base=f'experiments/S012/{PRIOR}/deliveries/COMPONENTS/1';old=read(self.root/base/'delivery.json')['content']
        paths={};attachments=[]
        for raw in old['attachments']:
            item=EvidenceFile.from_dict(raw);source=f'{base}/{item.reference.path}'
            if digest(self.root/source)!=item.reference.sha256:raise ValueError('changed predecessor attachment')
            dest=f'attachments/historical/{PRIOR}/{item.reference.path.removeprefix("attachments/")}'
            paths[item.reference.path]=dest
            attachments.append(EvidenceFile(source,replace(item.reference,path=dest)))
        fids={v['fact_id']:f'P39__{v["fact_id"]}' for v in old['facts']}
        facts=[FactValue.from_dict(remap(v,paths,fids)) for v in old['facts']]
        panel=ComponentPanel.from_dict(remap(old['payload'],paths,fids));entries=list(panel.components)
        exp=self.root/f'experiments/S012/{EID}';refs={}
        for name in ('01_goal.md','02_design.md','03_execution.md','04_conclusion.md','stage2_report.md',
                     'full_research_ledger.json','role_coverage.json','cycle_summary.json','phase_summary.json',
                     'domain_extension.json','hypothesis_judgments.json','experiment_binding.json','experiment.py',
                     'execution_driver.py','reproduction/verify.py','delivery.py','publication_driver.py',
                     'artifacts/verification/independent.json'):
            mime='text/markdown' if name.endswith('.md') else 'application/json' if name.endswith('.json') else 'text/x-python'
            ref=EvidenceRef(f'attachments/current/{EID}/{name}',digest(exp/name),mime);refs[name]=ref
            attachments.append(EvidenceFile(f'experiments/S012/{EID}/{name}',ref))
        auth='research/S012/materials/stage2_native_scope_authorization_20261006.json'
        attachments.append(EvidenceFile(auth,EvidenceRef('attachments/current/authorization.json',digest(self.root/auth),'application/json')))
        def evidence(name):return EvidenceRef(f'experiments/{EID}/{name}',digest(exp/'artifacts/rex'/name),'application/json')
        rr=evidence('opportunities.json');ar=evidence('annual.json');ph=evidence('phase_comparisons.json')
        receipt=read(exp/'artifacts/rex/execution_receipt.json')
        definition=ExperimentDefinitionRef(EID,receipt['definition_sha256'],receipt['source_sha256'],'experiment:Experiment')
        rows=read(exp/'artifacts/rex/opportunities.json')
        for key,j in read(exp/'hypothesis_judgments.json').items():
            r=next(x for x in rows if (x['signal'],x['horizon'],x['delay'],x['fee'])==(j['signal'],5,0,.001));ids=[]
            for field in ('eligible_days','events','net_mean','same_window_mean','potential_events','potential_fills','potential_limit_net','potential_per60'):
                fid=f'{EID}_{key}_{field}';ids.append(fid);value=r[field]
                facts.append(FactValue(fid,value,'count' if field in ('eligible_days','events','potential_events','potential_fills')
                    else 'potential/60sessions' if field=='potential_per60' else 'decimal return',
                    FactStatus.AVAILABLE if value is not None else FactStatus.INSUFFICIENT_DATA,(rr,),None if value is not None else '无成熟事件'))
            test=ComponentTestResult(f'{EID}_{key}',EID,refs['02_design.md'],ComponentTestStatus(j['status']),j['judgment'],
                (rr,ar,ph,refs['04_conclusion.md']),tuple(ids))
            entries.append(ComponentEntry(f'CURRENT_{EID}_{key}',definition,'收益机会或确认用途复核',
                '费用后开盘事件与固定相位限价零填贡献，非账户','主5日；1/3/5/10日和延迟/费用全部冻结对照',
                '原生及共同可得域分别报告，六种比较同日历；所有h+1相位和去单年',
                '原定义T17可知、原可得政策及有效位继承；未知支路不作无机会',
                '518850原始OHLCVA，前收盘向下取整到0.001价格档（通常等于前收盘）潜在限价，不是净值或真实成交',
                '全部开发池已见；源时点、年度、费用与分钟异常保持；没有独立样本外证明',j['judgment'],(test,)))
        summary=read(exp/'cycle_summary.json')
        for field in ('panel_records','recommended_distinct_components','opportunity_count','risk_state_count','confirmation_count','paths','annual_rows','phase_rows','independent_fields_checked'):
            facts.append(FactValue(field,summary[field],'count',FactStatus.AVAILABLE,(refs['cycle_summary.json'],)))
        if len(entries)!=147:raise ValueError('full inherited panel count differs')
        conclusion='阶段二完成147条记录：推荐O01/M05两收益机会、C01/C02/C03三风险状态；Q07调整为可选确认候选。原生动量潜在净负，互补年度/费用敏感，无新增独立推荐机会。完整账户目标待阶段三获批验证。'
        return DeliveryContent(ComponentPanel(tuple(entries),conclusion),DeliveryStatus.COMPLETE,tuple(facts),
            (Explanation(ExplanationKind.RESEARCH_JUDGMENT,conclusion,supporting=(refs['stage2_report.md'],refs['role_coverage.json']),
                         contrary=(refs['phase_summary.json'],refs['full_research_ledger.json'])),
             Explanation(ExplanationKind.FACT,'共同域信号完全一致；原生M05额外3成熟事件及动量额外190事件净负，范围增量不等于因子增量。',supporting=(refs['domain_extension.json'],)),
             Explanation(ExplanationKind.STATISTICAL_EVIDENCE,'全部已见开发池，所有期限/相位保留；Q07日历贡献反证及并集去2025负不新增用户经济硬门。',supporting=(refs['phase_summary.json'],refs['04_conclusion.md']))),
            ReproductionSpec('仓库根运行本实验reproduction/verify.py；正式重跑须新后继实验。',
                (refs['experiment_binding.json'],),'同版本numpy/pandas与完整S012正式制品闭包；不重取行情。',
                'worker=1/native_threads=1/seed12041；潜在成交、重叠相位、历史发布时间及账户达标不能由技术PASS证明。'),
            attachments=tuple(attachments))
