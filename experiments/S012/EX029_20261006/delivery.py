"""Publish a new, explicitly partial component census; old revisions remain intact."""
from pathlib import Path
from hashlib import sha256
import json
from czsc_trader.research_tools import (
    ComponentEntry,ComponentPanel,ComponentTestResult,ComponentTestStatus,
    DeliveryContent,DeliveryDefinition,DeliveryReference,DeliveryStage,DeliveryStatus,
    EvidenceFile,EvidenceRef,ExperimentDefinitionRef,ExperimentEvidenceRef,
    ExperimentEvidenceUse,ExperimentOwner,Explanation,ExplanationKind,FactStatus,
    FactValue,ReproductionSpec,ResearchDeliverable)

EID='EX029_20261006'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()

class ReframedComponents(ResearchDeliverable[ComponentPanel]):
    def __init__(self,root):self.root=Path(root).resolve()
    @property
    def definition(self):
        refs={}
        def visit(eid):
            if eid in refs:return
            path=f'experiments/S012/{eid}/artifacts/rex'
            receipt=read(self.root/path/'execution_receipt.json')
            refs[eid]=ExperimentEvidenceRef(eid,path,receipt['receipt_sha256'],
                ExperimentEvidenceUse.CURRENT_EVALUATION if eid==EID else ExperimentEvidenceUse.HISTORICAL_REFERENCE)
            for parent in receipt['predecessor_receipts']:visit(parent)
        visit(EID)
        priors=tuple(DeliveryReference.from_dict(read(self.root/f'experiments/S012/{eid}/deliveries/{stage}/1/receipt.json')['reference'])
                     for eid,stage in (('EX019_20261005','COMPONENTS'),('EX028_20261006','CANDIDATES')))
        return DeliveryDefinition(ExperimentOwner('S012',EID),DeliveryStage.COMPONENTS,1,
                                  predecessors=priors,experiments=tuple(refs[k] for k in sorted(refs)))
    def build(self):
        root=self.root;exp=root/f'experiments/S012/{EID}';p=exp/'artifacts/rex'
        files=[];refs={}
        for name in ('01_goal.md','02_design.md','03_execution.md','04_conclusion.md',
                     'hypothesis_ledger.json','hypothesis_judgments.json','protocol_count_correction.md',
                     'external_advice_review.md','resource_gap_proposal.md','tushare_resource_verification.md',
                     'tushare_inventory.json','artifacts/verification/independent.json','reproduction/verify.py',
                     'delivery.py','execution_driver.py','experiment_binding.json'):
            ref=EvidenceRef('attachments/current/'+name,digest(exp/name),'text/markdown' if name.endswith('.md') else 'application/json' if name.endswith('.json') else 'text/x-python')
            files.append(EvidenceFile(f'experiments/S012/{EID}/{name}',ref));refs[name]=ref
        auth='research/S012/materials/first_principles_stage2_authorization_20261006.json'
        files.append(EvidenceFile(auth,EvidenceRef('attachments/current/authorization.json',digest(root/auth),'application/json')))
        def evidence(name):return EvidenceRef(f'experiments/{EID}/{name}',digest(p/name),'application/json')
        result_ref=evidence('opportunities.json');annual_ref=evidence('annual.json');infer_ref=evidence('inference.json')
        receipt=read(p/'execution_receipt.json')
        definition=ExperimentDefinitionRef(EID,receipt['definition_sha256'],receipt['source_sha256'],'experiment:Experiment')
        judgments=read(exp/'hypothesis_judgments.json');specs=read(p/'hypothesis_definitions.json')
        rows=read(p/'opportunities.json');inference={x['signal']:x for x in read(p/'inference.json')}
        components=[];facts=[]
        for spec in specs:
            key=spec['id'];row=next(x for x in rows if x['signal']==key and x['horizon']==spec['primary_horizon'] and x['delay']==0 and x['fee']==.001)
            ids=[]
            for field in ('events','net_mean','parent_lift','matched_increment','ols_increment','nonoverlap_events',
                          'limit_potential_fills','limit_potential_net','potential_per60_original1535'):
                fid=key+'_'+field;value=row[field];ids.append(fid)
                facts.append(FactValue(fid,value,'count' if field.endswith('events') or field=='limit_potential_fills' else 'cycles/60sessions' if field=='potential_per60_original1535' else 'decimal return',
                    FactStatus.AVAILABLE if value is not None else FactStatus.INSUFFICIENT_DATA,(result_ref,),None if value is not None else '无可计算事件或完整控制矩阵'))
            fid=key+'_q';ids.append(fid);value=inference[key]['q']
            facts.append(FactValue(fid,value,'BH diagnostic',FactStatus.AVAILABLE,(infer_ref,)))
            test=ComponentTestResult(key+'_fixed_primary',EID,refs['02_design.md'],ComponentTestStatus(judgments[key]['status']),
                judgments[key]['judgment'],(result_ref,annual_ref,infer_ref,refs['protocol_count_correction.md']),tuple(ids))
            components.append(ComponentEntry('FP_'+key,definition,spec['role'],spec['hypothesis'],f"{spec['primary_horizon']}交易日主期限；1/3/5/10/20描述对照",
                spec['parent']+'同费用及状态匹配/OLS',
                'T17:00；FX源日+2自然日08:00，其他美国源严格前日，本地份额次中国交易日；均为披露政策',
                '518850原始价格；美元黄金与离岸汇率代理；相对现货/同类比值非净值溢价',
                '全部已见上市历史开发池；重叠事件、未验证账户；用途限于后继机制研究',judgments[key]['judgment'],(test,)))
        for key,label,role in (
            ('DXY','美元篮子变化及DXY×VIX联合','机会环境'),('GVZ','VIX/GVZ相对预期波动','风险/确认'),
            ('GLOBAL_FLOW','全球黄金ETF吨数/净流入变化','确认'),('COT','COMEX黄金净持仓与拥挤','机会/风险状态'),
            ('CENTRAL_BANK','央行购金低频状态','机会环境'),('COMMODITY_RATIOS','黄金/铜、黄金/油相对强度','竞争解释')):
            components.append(ComponentEntry('GAP_'+key,definition,role,label,'待获批接入后固定主期限',
                '须与原始单项、黄金/汇率及价格状态竞争','尚缺获批逐日或逐期真实可得历史','缺口，不使用代理冒充原序列',
                '本轮未接入也未检验', '缺资源；不判断机制有效或无效。',
                (ComponentTestResult(key+'_not_tested',EID,refs['resource_gap_proposal.md'],ComponentTestStatus.INSUFFICIENT_DATA,
                   '未纳入正式输入，数据权限及实现路线待确认。',(evidence('coverage.json'),refs['tushare_resource_verification.md'])),)))
        facts.extend(FactValue(name,value,'count',FactStatus.AVAILABLE,(evidence('coverage.json'),)) for name,value in
                     (('sessions',1535),('fixed_hypotheses',19),('controls',11),('paths',600),('annual_rows',4200)))
        conclusion='第一性原理假设重建及首轮普查完成；本轮无新确认有效机会。M05避险时变确认与M01趋势质量保留线索，资源与跨状态复验未完成，阶段二IN_PROGRESS。'
        return DeliveryContent(ComponentPanel(tuple(components),conclusion),DeliveryStatus.PARTIAL,tuple(facts),(
            Explanation(ExplanationKind.RESEARCH_JUDGMENT,conclusion,supporting=(refs['04_conclusion.md'],),contrary=(annual_ref,infer_ref)),
            Explanation(ExplanationKind.RESEARCH_JUDGMENT,'原39组件记录及阶段三空达标集合为前驱历史；本面板只呈现新19检验和6资源缺口，不改写历史或确认新可交接组件。',supporting=(refs['01_goal.md'],refs['04_conclusion.md'])),
            Explanation(ExplanationKind.STATISTICAL_EVIDENCE,'19主假设增量区间均跨0；多重比较、费用、延迟和年度为诊断，未新增经济硬门。',supporting=(infer_ref,refs['04_conclusion.md'])),
            Explanation(ExplanationKind.FACT,'固定源码及机器定义实际19假设；原描述数量18为文字误计，600/4200/BH19以真实制品为准，源定义及计算未变。',supporting=(refs['protocol_count_correction.md'],evidence('hypothesis_definitions.json')))),
            ReproductionSpec('仓库根运行reproduction/verify.py核验全路径；正式重跑按原协议在新实验目录执行，保留原回执。',
                (refs['02_design.md'],refs['protocol_count_correction.md'],refs['experiment_binding.json']),
                '绑定S012实际前驱REX制品及原DFLS来源；未接入新增市场来源。',
                'worker=1、native_threads=1、seed=12029；全部已见开发池，时间假设及日线潜在触价边界保留。'),
            incomplete_items=('DXY与GVZ资源选择和DEV契约变更待批准，全球资金/持仓/央行/商品比值未检验。',
                              'M05/M01需跨状态及真实发布时间后继验证；无新成熟有效收益组件，原三个账户目标未重验。'),
            attachments=tuple(files))
