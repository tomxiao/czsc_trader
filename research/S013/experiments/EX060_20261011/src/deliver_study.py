"""Close EX060 phase-two evidence, retaining positive and negative findings."""
from pathlib import Path
import json
import shutil
import sys
import numpy as np
import pandas as pd
from czsc_trader.application import assemble_delivery, validate_delivery, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-redesign-absolute'
sys.path.insert(0,str(ROOT/'research/S013/experiments/EX058_20261011/src'))
import common  # noqa: E402


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    ctx=common.context(1)
    exp=ExperimentRef.from_dict(read(WORK/'experiment.json'))
    path=exp.resolve(ROOT)
    assert not (path/'protocols/delivery_reference.json').exists()
    refs={}
    for name in ('method','technical_v2','technical_v3','technical_v4','input','result'):
        refs.update(read(path/f'protocols/{name}_references.json'))
    audit=read(WORK/'absolute_audit.json')
    stats=read(WORK/'compact_statistics.json')
    judgment=read(WORK/'component_judgment.json')
    verification=read(WORK/'verification.json')
    assert verification['status']=='PASS'
    old=read(ROOT/'research/S013/assets/runs/EX058_20261011/parameter_analysis.json')
    pointrows=[]
    for label, candidate in (('B0-TIME','C2132'),('N0','C8880')):
        summary=next(r for r in audit['centers'] if r['candidate_id']==candidate)
        analysisref=EvidenceRef.from_dict(summary['analysis_ref'])
        analysisref.resolve(ROOT)
        refs[candidate+'-old-parameter-analysis']=analysisref.to_dict()
        rows=old['points'][label]
        assert len(rows)==32
        for item in rows:
            assert item['qualified']==all(item['gates'].values())
            for key,value in item['gates'].items():
                assert type(value) is bool
            native=EvidenceRef.from_dict(item['reference'])
            native.resolve(ROOT)
            pointrows.append({'center':candidate,'point':item['point_index'],'candidate':item['candidate_id'],
                'net_cagr':item['net_cagr'],'full_drawdown':item['drawdown'],'closed_trades':item['closed_trades'],
                'frequency60':item['frequency60'],**item['gates'],'all_four':item['qualified'],
                'return_2022':item['annual']['2022']['return'],'return_2023':item['annual']['2023']['return'],
                'native_evidence_sha256':native.sha256})
        assert np.isclose(np.quantile([r['net_cagr'] for r in rows],.1),summary['q10_cagr'])
        assert np.isclose(np.quantile([r['drawdown'] for r in rows],.9),summary['q90_drawdown'])
        for gate,count in summary['gate_pass_counts'].items():
            assert sum(r['gates'][gate] for r in rows)==count
    pd.DataFrame(pointrows).to_csv(WORK/'baseline_32_point_gates.csv',index=False,float_format='%.17g')
    worsening=0
    for scope in ('all','opportunity'):
        for label in ('downside_3','downside_5'):
            models=stats[scope][label]['models']
            worsening+=sum(models[name]['mse']>models['controls']['mse'] for name in ('controls+intraday','controls+overnight','controls+both'))
    assert worsening==12
    conclusion={'status':'PHASE_TWO_COMPLETE_NO_NEW_STRATEGY', 'robust_strategy_goal_achieved':False,
        'priority':'Improve net-CAGR Q10 and full drawdown Q90; report32 individual original-gate pass rates; no added hard gate',
        'baseline':'C8880 is the unique absolute-tail frontier among six historically qualified centers',
        'new_components':'Both fixed20 short-horizon components lack stable incremental evidence for strategy use',
        'risk_model_worsening_comparisons':12,'new_financial_accounts':0,'new_parameter_points':0,
        'old_parameter_accounts_audited':224, 'old_baseline_parameter_accounts_reused_for_display':64,
        'judgment':judgment, 'next_step':'停止本两条组件的扫参。若继续研究，应从独立交易机会或收益与风险的共同表达重新提出信息假说，不能由本次结果推出所有重设计不可能。',
        'economic_targets_unchanged':True,'sealed_validation_used':False,'external_data_used':False,
        'production_or_platform_changes':False}
    common.write(WORK/'conclusion.json',conclusion)
    lines=['# EX060：按扰动绝对收益与回撤重新审视C2132，并回到阶段二检验风险组件','',
        '本轮证据审计与组件验证已完成；“达标且稳健”的策略目标仍未达成。原四项经济要求保持不变。优先提高收益Q10、降低全区间回撤Q90，不再要求相对中心的退化量同步改善，也未新增硬门。','',
        '## 1. 已有研究取得了实际改善，但还不够','',
        '原S013开发池2020-01-02至2026-09-30，共1636个交易日，100万元，每侧费用0.1%，固定1% LimitBuyHold基准，HFQ_RESEARCH后复权及2019-12-31锚点。以下不是EX059共同区间比较，不能与该比较的数值混用。',
        'Q10和Q90由原13维完整参数域上的同32组5%标准化总L2扰动计算，seed13，linear分位数。它们表示这些固定扰动样本较差一端的表现，并不是未来发生概率或收益保证。','',
        '| 指标 | C2132 | C8880（EX058） |','|---|---:|---:|',
        '| 中心净年化收益 | 16.1572% | 17.1346% |',
        '| 中心全区间最大回撤 | 14.1599% | 13.6187% |',
        '| 扰动净年化收益Q10，越高越好 | 5.8974% | 6.3981% |',
        '| 扰动全区间回撤Q90，越低越好 | 30.5044% | 28.3508% |','',
        'C8880收益Q10提高0.5007个百分点，回撤Q90降低2.1537个百分点；32组同坐标对照中，30组收益更高，30组回撤更低。六个历史中心达标方案中，C8880是此绝对尾部口径下唯一未被其他方案同时压过的方案。此前相对中心收益退化略变差，使其未通过旧的联合改善判断；历史判断保留不变，新的用户偏好另行记录。','',
        '| 原四项目标 | C2132达标数/32 | C8880达标数/32 |','|---|---:|---:|',
        '| 净年化收益达到基准的1.5倍，即10.8290% | 2（6.25%） | 7（21.875%） |',
        '| 每一年度回撤严格低于基准 | 32（100%） | 32（100%） |',
        '| 每60个交易日至少4次闭合交易 | 23（71.875%） | 27（84.375%） |',
        '| 基准亏损年份策略均盈利 | 0（0%） | 2（6.25%） |',
        '| 同时满足四项 | 0（0%） | 0（0%） |','',
        '主要缺口是收益和弱年份盈利的兼容性。C8880在2022年14/32组盈利、2023年仅5/32；2023年扰动收益平均−3.3915%，Q10为−7.8918%。两组同时在2022/2023盈利的方案，其净年化10.1780%和10.4484%仍低于10.8290%门槛。年度回撤目标通过，并不意味着全区间回撤Q90已令人满意。','',
        '完整64行逐点指标与四门布尔值见正式证据baseline-32-point-gates；复用旧账户，不重新运行或重复计数。','',
        '## 2. 为什么回到阶段二','',
        '原范围位置负责寻找回落后的机会，ACF和买入确认影响是否进场，持有时限负责退出。小改参数会改变第一次进出场、持仓状态及后续路径，难以只靠局部微调稳定收益。既有删除ACF、删除定时退出、简单平滑/投票、波动时钟和振幅止损等研究已经有反证，见历史审计及组件设计证据。',
        '本次检验新的信息，而不把过去失败的波动时钟重新包装：①20日30分钟下行能量占比，衡量日内路径的下行能量分布；②20日隔夜负跳空RMS，衡量近期隔夜下跌幅度。它们不是账户收益指标。','',
        '## 3. 新组件检验结果','',
        '事前固定2组件、3/5日收益和不利波动及次日负跳空共5标签、9项原信息控制、4个固定模型。2020用于初始训练，2021—2026逐年预测；训练标签必须在首个测试信号日前成熟，阈值及排名只使用训练历史。全池为主，原C8880 entry_eligible机会池为辅助，机会池受旧策略状态路径影响，不按盈利样本筛选。','',
        '| 风险标签，全池 | 日内下行能量：控制后秩相关 | 隔夜负跳空RMS：控制后秩相关 |','|---|---:|---:|',
        '| 未来3日不利波动 | −0.0402 | −0.0026 |',
        '| 未来5日不利波动 | −0.0359 | −0.0056 |','',
        '隔夜组件与3/5日不利波动的原始秩相关分别0.1274/0.1139；控制价格方向、波动、当前日内/隔夜变化、日内总能量及原买入确认后接近零。这支持“主要重复已有波动信息”的解释，尚不足证明完全冗余或任何非线性表达都无效。',
        '更直接的反证是：全池及机会池、3日及5日风险的四模型对照中，加入日内、加入隔夜、同时加入两者，共12个增广比较，合并年度预测误差全部比原九项信息更大。各年度和不重叠相位方向也不稳定。两范围×五标签×两组件共20个控制后相关区间均跨零，仅用于描述不确定性，不作为新增验收硬门。','',
        '正面证据同样保留：隔夜指标高组的后续不利波动确实较大，全池3/5日高减低为0.8107/1.0458个百分点，机会池为0.8054/0.5110个百分点；日内组件略改善机会池次日负跳空方向预测误差，约0.7934%。但“有风险分层”尚未证明提供额外信息，次日开盘跳空标签也不是能用次日开盘成交避免的持仓当夜损失。局部年份改善不能代替跨年增量。','',
        '2023机会池日内低组仅15例、隔夜高组0例，不能声称该年保护有效；2022最小相关组21例，标签重叠，不能当作21个独立样本；2026机会池5日标签仅19例，明确记为样本不足。分位分组可因并列阈值重叠，完整输出保留组数和原因。','',
        '判断：停止本次两个固定组件的策略化和门槛搜索。这是基于缺乏稳定增量及预测退化的研究判断，不是新经济硬门，也不证明所有重设计都不可能。','',
        '## 4. 验证范围与局限','',
        '公开DFLS重取固定资产；30m共13088根，1636日每天8根，完整日历一致；首Open/末Close与日线一致；公开ExecutionPricing转换与原账户数据完全一致；C8880原账户缓存与已发表原生证据序列化完全相同，原确认分未改写。没有新provider调用。',
        '组件信号日期2020-01-02至2026-09-29共1635日，9/30仅用于标签；原账户验收仍为1636执行日。30m缺少开发池之前的历史，因此首19日相关组件保持缺失，不补造；3/5日标签尾部保持缺失。旧5个30m High/Low偏差原样保留，组件只用Open/Close，风险标签采用日线Low。',
        '17项纯组件检查、24项纯统计检查及8项非法输入拒绝用例通过；真实CSV独立相关复算、实际训练成熟日期和保留预测误差共120项检查通过。当前纯组件、纯统计、修正版执行器及交付器Ruff通过；早期执行器的输入适配失败保留，均发生在真实统计前，统计方法未修改。',
        '已见开发池被反复研究；年度时间顺序预测仍不是独立封存验证。T17可用为现有数据政策，历史真实发布时间及修订未独立验证。价格标签未扣费用、未模拟限价成交或复投，不能宣称新收益改善。阶段二未启动新账户、参数32点或五项策略自检。','',
        '## 5. 保留什么，停止什么','',
        '保留C2132作为原机制基线、C8880作为目前绝对尾部最优的研究基线，保留旧ACF、确认及定时退出的可核查作用证据；不把任何基线认定为已稳健达标。停止继续围绕失败的两个组件扫阈值，以及缺乏新依据的简单平滑、投票和波动时钟重复试验。',
        '若继续，应重新提出独立盈利机会或收益与风险的共同表达假说，再检验其增量；仅增加“少买一点”的过滤条件，容易同时损失收益和交易频率。现阶段没有足够证据支持具体新策略。平台当前FROZEN_RULE仅表达0/1仓位，动态分层仓位或部分退出需要单独DEV能力授权，本轮未修改平台。','',
        '本轮收口：证据审计与两条组件实验完成，稳健达标目标未完成。下一步建议更换信息假说和策略表达，避免继续加补丁；不自动把本轮负面结果当作已完成整个策略目标。','']
    report='\n'.join(lines)
    (path/'others/report.md').write_text(report,encoding='utf-8',newline='\n')
    for name in ('baseline_32_point_gates.csv','compact_statistics.json','component_judgment.json','verification.json','conclusion.json'):
        f=WORK/name
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name.split('.')[0].replace('_','-'),f.read_bytes(),
            'text/csv' if name.endswith('.csv') else 'application/json',f.suffix[1:])).to_dict()
    for name in ('verify_results.py','deliver_study.py'):
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name.removesuffix('.py').replace('_','-'),(WORK/name).read_bytes(),'text/x-python','py')).to_dict()
        shutil.copyfile(WORK/name,path/'src'/name)
    evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(r) for r in refs.values()))
    for r in evidence:
        r.resolve(ROOT)
    entries=[]
    for component,func,status,explanation in (
        ('INTRADAY_DOWN_ENERGY20','intraday_downside_energy',d.ComponentTestStatus.INEFFECTIVE,'固定20日下行能量没有稳定跨年增量；加入风险模型全池/机会均退化；次日跳空诊断微弱改善完整保留'),
        ('OVERNIGHT_DOWN_ENERGY20','overnight_downside_risk',d.ComponentTestStatus.INEFFECTIVE,'描述性风险分层存在，但控制旧信息后增量接近零；风险模型误差更差；不能证明2023保护')):
        entries.append(d.ComponentEntry(component,d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['component_definitions.py']),func),
            '前向短期风险描述与潜在入场/持仓风险信息', 'return_3,return_5,downside_3,downside_5,negative_gap_next',
            'T+1 OPEN入场，持有完整3/5交易日后OPEN退出；次日负跳空单独诊断',
            '9项方向/波动/路径总能量及原确认控制；4固定alpha10秩回归对照',
            'T17全部8根30m完结与日线政策，T+1执行；未独立验证历史发布时间',
            'HFQ_RESEARCH，原2019-12-31 anchor0.2803；价格标签不是费用后账户收益',
            'S013已见开发池1635信号日；首19日缺失不填补；年度顺序验证不是封存验证',explanation,
            (d.ComponentTestResult(component+'-fixed-study',exp.experiment_id,EvidenceRef.from_dict(refs['plan.json']),status,explanation,
                (EvidenceRef.from_dict(refs['statistics.json']),EvidenceRef.from_dict(refs['component_judgment.json']),EvidenceRef.from_dict(refs['verification.json']))),)))
    formal_report=report+'\n## 正式证据引用\n\n'
    for name,ref in refs.items():
        r=EvidenceRef.from_dict(ref)
        formal_report+=f'- [{name}](../../../assets/deliveries/COMPONENTS/2/{r.path})\n'
    mandate=d.DeliveryReference.from_dict(read(ROOT/'research/S013/materials/stage1_mandate_reference_r5_20261008.json'))
    previous=d.DeliveryReference.from_dict(read(ROOT/'research/S013/deliveries/COMPONENTS/1/receipt.json')['reference'])
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.COMPONENTS,2,(mandate,previous)),
        d.DeliveryContent(d.ComponentPanel(tuple(entries),'阶段二检验完成；两固定组件不足以支持新策略；基线绝对尾部已改善但原四门联合0/32，稳健达标目标未完成'),
                          d.DeliveryStatus.COMPLETE,(),(),report=formal_report,evidence=evidence))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS',validation.to_dict()
    common.write(path/'protocols/delivery_reference.json',receipt.reference.to_dict())
    common.write(path/'protocols/delivery_validation.json',validation.to_dict())
    common.write(path/'protocols/final_evidence_references.json',refs)
    print({'phase_two':'COMPLETE','FULL':'PASS','new_accounts':0,'strategy_goal_achieved':False,'reference':receipt.reference.to_dict()},flush=True)


if __name__=='__main__':
    main()
