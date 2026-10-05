"""Opportunity-focused successor panel; preserves and qualifies prior evidence."""
import json
from hashlib import sha256
from pathlib import Path
from czsc_trader.research_tools import (
    ComponentEntry,ComponentPanel,ComponentTestResult,ComponentTestStatus,
    DeliveryContent,DeliveryDefinition,DeliveryReference,DeliveryStage,DeliveryStatus,
    EvidenceFile,EvidenceRef,ExperimentDefinitionRef,ExperimentEvidenceRef,ExperimentEvidenceUse,
    ExperimentOwner,Explanation,ExplanationKind,FactStatus,FactValue,ReproductionSpec,ResearchDeliverable)

class S012Opportunities(ResearchDeliverable[ComponentPanel]):
    def __init__(self,root:Path):self.root=root
    def read(self,path):return json.loads((self.root/path).read_text(encoding='utf-8'))
    @property
    def definition(self):
        old=self.read('research/S012/materials/components_v1_validation.json')['reference']
        refs=[]
        for eid in ('EX001_20261004','EX003_20261004','EX004_20261004','EX005_20261004','EX006_20261004','EX007_20261004','EX008_20261004','EX010_20261004'):
            path=f'experiments/S012/{eid}/artifacts/rex';r=self.read(path+'/execution_receipt.json')
            refs.append(ExperimentEvidenceRef(eid,path,r['receipt_sha256'],ExperimentEvidenceUse.CURRENT_EVALUATION if eid=='EX010_20261004' else ExperimentEvidenceUse.HISTORICAL_REFERENCE))
        return DeliveryDefinition(ExperimentOwner('S012','EX010_20261004'),DeliveryStage.COMPONENTS,1,
            predecessors=(DeliveryReference.from_dict(old),),experiments=tuple(refs))

    def build(self):
        def attach(source,name,media='application/json'):
            return EvidenceFile(source,EvidenceRef('attachments/'+name,sha256((self.root/source).read_bytes()).hexdigest(),media))
        attachments=(
            attach('experiments/S012/EX010_20261004/02_design.md','corrected_protocol.md','text/markdown'),
            attach('experiments/S012/EX007_20261004/02_design.md','opportunity_protocol.md','text/markdown'),
            attach('experiments/S012/EX008_20261004/02_design.md','gold_protocol.md','text/markdown'),
            attach('experiments/S012/EX010_20261004/04_conclusion.md','research_report.md','text/markdown'),
            attach('experiments/S012/EX006_20261004/02_design.md','census_protocol.md','text/markdown'),
            attach('experiments/S012/EX008_20261004/04_conclusion.md','time_failure.md','text/markdown'),
            attach('experiments/S012/EX009_20261004/artifacts/rex/execution_failure.json','snapshot_failure.json'),
            attach('research/S012/materials/opportunity_authorization_20261004.json','authorization.json'),
            attach('experiments/S012/EX010_20261004/delivery.py','delivery.py','text/x-python'),
            attach('experiments/S012/EX005_20261004/02_design.md','prior_risk_protocol.md','text/markdown'),
        )
        def evidence(eid,name):
            path=self.root/f'experiments/S012/{eid}/artifacts/rex/{name}'
            return EvidenceRef(f'experiments/{eid}/{name}',sha256(path.read_bytes()).hexdigest(),'application/json')
        eid='EX010_20261004';fx=evidence(eid,'fx/opportunities.json');gold=evidence(eid,'gold/opportunities.json')
        annual=evidence(eid,'fx/annual.json');sens=evidence(eid,'fx/sensitivity.json');limit=evidence(eid,'fx/limit_events.json')
        time=evidence(eid,'data_audit.json');snapshot=evidence(eid,'snapshot_revision.json')
        old=evidence('EX005_20261004','robustness.json');census=evidence('EX006_20261004','opportunities.json')
        invalid=evidence('EX008_20261004','opportunities.json')
        receipt=self.read(f'experiments/S012/{eid}/artifacts/rex/execution_receipt.json')
        def definition(symbol):return ExperimentDefinitionRef(eid,receipt['definition_sha256'],receipt['source_sha256'],symbol)
        specs=(
            ('O01_FX_DIP','fx.masks:fx_q75_dip_q25','有条件的低频收益机会候选','3/5日次开盘收益；1/10日为期限反证',
             'SUPPORTED','强汇率支持叠加ETF回调：保守可得边界后5日净0.779%、匹配毛增量0.722%；支持开发池机会线索。q=0.280，限价去重1.10次/60日，尚不能作为已确认独立Alpha。',(fx,annual,sens,limit,time)),
            ('O02_FX_CALENDAR','fx.masks:fx_session_dip_q25','O01的时间尺度敏感性定义','3/5日次开盘收益',
             'REDUNDANT','改用5个ETF交易日计算汇率仍同向，属于O01同一信息来源，不重复算独立机会。',(fx,annual,sens,limit)),
            ('O03_FX_ALONE','fx.masks:fx_q75_all','汇率支持的方向性候选','3/5日次开盘收益',
             'INSUFFICIENT_DATA','5日净0.577%、匹配扣费后增量0.191%；3日开盘事件密度5.65/60日但扣费后增量仅0.030%，年度与实际限价容量仍弱。',(fx,annual)),
            ('O04_TURN','fx.masks:dip_turn','回调后转强的入场候选','3/5日次开盘收益',
             'INSUFFICIENT_DATA','5日净0.342%，但匹配扣费后增量仅0.007%，不能将市场本身上涨当作择时优势。',(fx,annual,sens,limit)),
            ('O05_SGE_RELATIVE','fx.masks:sge_cheap','相对境内黄金价格修复候选','3/5日次开盘收益',
             'INSUFFICIENT_DATA','5日净0.363%，匹配扣费后增量仅0.004%；SGE比值不代表ETF净值折溢价。',(fx,annual,sens,limit)),
            ('O06_BROAD_FX','fx.masks:fx_positive_dip_negative','扩大机会密度的竞争条件','3/5日次开盘收益',
             'INEFFECTIVE','放宽后5日匹配扣费后增量-0.165%；前收盘限价去重事件净-0.467%，增加密度稀释质量。',(fx,annual,limit)),
            ('O07_OVERSEAS_GOLD','gold.build','境外黄金补涨与相对价格修复','盘前决定后的1/3/5/10日开盘收益',
             'INSUFFICIENT_DATA','原强信号受时间语义污染；保守可用时间后大部分扣费增量转负，少量正事件不足以成为独立机会。',(gold,time,invalid)),
            ('O08_BREAKOUT','base.signals:breakout20/breakout_volume/compression_breakout','突破延续的竞争解释','3/5日次开盘收益',
             'INEFFECTIVE','EX006固定价量条件在主要期限未提供足够费用后增量；相关检验不依赖受影响的FX字段。',(census,)),
            ('R01_AUXILIARY','base.features','原波动、趋势后回撤、冲击集中度风险/状态辅助','风险3/5/10/20日；收益状态10/20日',
             'SUPPORTED','继承EX005三项角色证据；原风险定义及证据不依赖FXCM数据，不作为本轮新机会数。',(old,)),
        )
        entries=[]
        for cid,symbol,role,label,status,judgment,ev in specs:
            test_eid='EX005_20261004' if cid=='R01_AUXILIARY' else 'EX006_20261004' if cid=='O08_BREAKOUT' else eid
            evdef=definition(symbol.split(':')[0])
            if test_eid!=eid:
                r=self.read(f'experiments/S012/{test_eid}/artifacts/rex/execution_receipt.json')
                evdef=ExperimentDefinitionRef(test_eid,r['definition_sha256'],r['source_sha256'],'analysis.analyze' if test_eid.startswith('EX006') else 'experiment.analyze')
            protocol_index=9 if cid=='R01_AUXILIARY' else 4 if cid=='O08_BREAKOUT' else 0
            tests=[ComponentTestResult(cid+'_ROLE',test_eid,attachments[protocol_index].reference,
                ComponentTestStatus(status),judgment,ev)]
            if cid=='O01_FX_DIP':tests.append(ComponentTestResult(cid+'_SUFFICIENCY',eid,attachments[0].reference,
                ComponentTestStatus.INSUFFICIENT_DATA,'年度有反例、平移多重q=0.280、限价机会容量不足；用户账户目标尚未验证。',(annual,sens,limit)))
            entries.append(ComponentEntry(cid,evdef,role,label,'按上述期限固定检验，全部为已见开发池',
                '同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。',
                'FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。',
                'ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。',
                '仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。',judgment,tuple(tests)))
        values=self.read(f'experiments/S012/{eid}/artifacts/rex/fx/opportunities.json')
        core=next(x for x in values if x['mechanism']=='fx_q75_dip_q25' and x['horizon']==5 and x['lag']==0)
        limits=self.read(f'experiments/S012/{eid}/artifacts/rex/fx/limit_events.json')
        lim=next(x for x in limits if x['mechanism']=='fx_q75_dip_q25' and x['horizon']==5 and x['limit_discount']==0)
        facts=tuple(FactValue(k,v,u,FactStatus.AVAILABLE,(e,)) for k,v,u,e in (
            ('fx_paths',168,'count',fx),('gold_paths',96,'count',gold),('opportunity_n',core['n'],'count',fx),
            ('opportunity_net5',core['net20'],'fraction',fx),('opportunity_increment5',core['matched_increment'],'fraction',fx),
            ('opportunity_surplus5',core['surplus_after20'],'fraction',fx),('opportunity_q',core['shift_q'],'probability',fx),
            ('limit_capacity60',lim['dedup_fills_per60'],'events_per_60_sessions',limit)))
        return DeliveryContent(ComponentPanel(tuple(entries),
            '本轮机会研究交付完成：一个有条件的低频机会候选、弱备选及竞争解释反证，原三项风险/状态组件作为辅助。当前机会能力不足以证明用户收益与频率目标，不建议直接进入阶段三。详见research_report.md。'),
            DeliveryStatus.COMPLETE,facts,(
                Explanation(ExplanationKind.FACT,'保守可用时间下完成168条FX与96条境外黄金路径，O01存在正向事件收益和匹配增量。',('fx_paths','gold_paths','opportunity_n','opportunity_net5','opportunity_increment5')),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT,'O01作为条件性机会候选保留；统计、年度、非重叠和限价约束仍不足，未确认独立Alpha或完整账户达标。',('opportunity_q','limit_capacity60'),supporting=(fx,),contrary=(annual,sens,limit)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT,'EX008强信号因源日不等于可用时刻而隔离，修订后境外金价的多数增量消失。',contrary=(attachments[5].reference,gold,invalid)),
                Explanation(ExplanationKind.FACT,'DFLS已显式发布保守可用时刻；历史发布时间仍未知。两行报价计数修订留证，全部OHLC与日期不变。',supporting=(time,snapshot)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT,'全历史开发池，多轮选择偏差未消除；每轮多重调整不能当作跨轮独立验证。原技术失败及旧交付原样保留。'),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT,'下一步优先补充可核验时点的黄金/ETF日内独立机会；阶段三及生产、推送均未执行。'),
            ),ReproductionSpec('先核验EX001—EX010档案及当前交付；复算须创建后继REX实验，按固定条件与显式AvailableDate执行，不覆盖已有回执或manifest。',
                (attachments[0].reference,attachments[1].reference,attachments[2].reference,attachments[8].reference),
                '数据经DFLS/Tushare取得；EX010新源数据与EX004前驱共同绑定。完整原始制品被Git忽略，跨机器复算需同步完整前驱链并验证哈希。',
                '条件与种子固定；浮点统计允许微小误差，身份哈希严格；供应商修订须新实验留证。'),attachments=attachments)
