"""Numerical reconciliation and honest report publication for a blocked formal delivery."""
from pathlib import Path
import sys
import os
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
SCRATCH=ROOT/'.tmp/s018-c9380-stage4-completion'
sys.pycache_prefix=str(SCRATCH/'pycache')
os.environ['TMP']=os.environ['TEMP']=str(SCRATCH)
from dataclasses import asdict
from hashlib import sha256
import json
import math
from time import perf_counter
from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,validate_experiment
from dataflows import ProviderConfig
from strategy_runtime.equity_definition import execution_spec_from_dict
from strategy_evaluator import CandidatePerformanceAssessmentRequest

WORK=Path(__file__).resolve().parents[1]
OUT=WORK/'others'
MATERIAL=ROOT/'research/S018/materials/c9380_stage4_completion'
OLD=ROOT/'research/S018/experiments/EX064_20261104'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')


def close(a,b):
    assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-11),(a,b)


def main():
    begun=perf_counter()
    assert not (WORK/'report_ref.json').exists(),'Published result must not be overwritten.'
    time=read(MATERIAL/'time_analysis.json')
    family=read(MATERIAL/'family_statistics.json')
    current=read(MATERIAL/'family_current_center_check.json')
    prior=read(OLD/'others/analysis_sensitivity.json')
    accounts=read(OLD/'others/recovery_01/results.json')['accounts']
    panel=read(OUT/'panel.json')
    row=panel['rows'][0]
    values={x['metric']:x['value'] for x in row['diagnostics']}
    request=CandidatePerformanceAssessmentRequest.from_dict(read(SCRATCH/'request.json'))
    assert request.sha256==panel['request_sha256']
    assert current['status']=='PASS' and all(current['checks'].values())
    assert family['new_strategy_accounts']==time['account_replays']==0
    assert len(row['parameter_performances'])==79
    assert prior['joint_passes']==prior['absolute_dd_passes']==79 and prior['required_joint_passes']==65
    for item in row['parameter_performances']:
        assert item['annual_return']/item['drawdown']>=1.25*item['benchmark_return']/item['benchmark_drawdown']
        assert item['drawdown']<=.9*item['benchmark_drawdown'] and item['drawdown']<=.25
    for metric,key in (('NET_ANNUAL_RETURN','annual'),('DRAWDOWN_MAGNITUDE','dd'),('FREQUENCY_MEDIAN','median')):
        close(values[metric],accounts['CENTER']['candidate'][key])
    close(values['PROFIT_CONCENTRATION'],time['concentration']['largest_positive_cycle_share'])
    close(values['PARAMETER_DRAWDOWN_Q90'],prior['quantiles']['dd_q90'])
    close(row['rolling_calmar_excess_q10']['value'],time['rolling']['excess_calmar_q10'])
    for key in ('lower_95','upper_95'):
        close(row['uncertainty'][key],time['paired_bootstrap']['cagr'][key])
    assert row['frequency_coverage']['covered_windows']==row['frequency_coverage']['total_windows']==902
    assert all(accounts['CENTER']['gates'].values()) and all(accounts['PRESSURE']['gates'].values())
    assert not (ROOT/'research/S018/deliveries/ASSESSMENT').exists()
    verification={'status':'PASS_RSCH_NUMERIC_RECONCILIATION','center_and_pressure_gates':'PASS',
        'parameter_points':79,'joint_passes':79,'required_passes':65,'all_point_risk_passes':79,
        'se_and_independent_time_concentration_bootstrap_agree':True,'exact_family_center_match':True,
        'request_matches_panel_hash':True,'new_account_replays':0,'formal_assessment_delivery':'BLOCKED',
        'comparison_result_fabricated':False,'se_family_diagnostics_unchanged':True,
        'remaining_role_authorization':'DEV mixed-parameter comparison contract only',
        'source_hashes':{p.name:sha256(p.read_bytes()).hexdigest() for p in
            (MATERIAL/'time_analysis.json',MATERIAL/'family_statistics.json',MATERIAL/'family_current_center_check.json',OUT/'panel.json')},
        'verification_seconds':perf_counter()-begun}
    save(OUT/'rsch_verification.json',verification)
    (WORK/'src/finalize.py').write_bytes((MATERIAL/'finalize.py').read_bytes())
    c=accounts['CENTER']['candidate']; pressure=accounts['PRESSURE']['candidate']; bh=accounts['CENTER']['benchmark']
    year_lines='\n'.join(f"|{y['start'][:4]}{' YTD' if y['start'][:4]=='2026' else ''}|{y['candidate']['total_return']:.2%}|{y['benchmark']['total_return']:.2%}|{y['candidate']['local_bar_drawdown']:.2%}|{y['candidate']['calmar']:.3f}|{y['benchmark']['calmar']:.3f}|" for y in time['years'])
    report=f'''# EX065：C9380 阶段四研究分析完成，正式交付受混合参数接口限制

五项自检的研究分析均已完成：沿用EX064参数与费用证据，本轮完成时间稳定性、收益集中性、成对区间和研究族选择偏差诊断，新增账户回放0次。C9380仍通过既定数值硬门，但跨时期优势不稳定，选择偏差与独立验证缺口仍存在。正式ASSESSMENT尚未发布：SE自检面板可计算，Calmar比较合同拒绝本次合法整数及固定类别参数；这是平台表达能力阻断，不是策略经济失败。

## 目标与既有自检

用户仅选定C9380进入阶段四，来源CANDIDATES/3中其余492个候选未在本次评估。既定目标为净卡玛，时间、集中性和统计诊断不新增硬门。标准净年化{c['annual']:.2%}、回撤{c['dd']:.2%}、净卡玛{c['calmar']:.6f}；同条件买持净年化{bh['annual']:.2%}、回撤{bh['dd']:.2%}、净卡玛{bh['calmar']:.6f}。95个闭合周期，60交易日中位6笔，902/902完整窗口至少3笔。

79/79个邻点同时满足净卡玛≥买持1.25倍及回撤≤买持0.9倍，要求至少65点；全部点回撤≤25%。每侧费用0.2%时，净年化{pressure['annual']:.2%}、回撤{pressure['dd']:.2%}、净卡玛{pressure['calmar']:.6f}，压力门槛通过。原79点与C9380定义保持不变，未重新选优。相同收益行为不作为独立成功。

## 时间稳定性

|期间|策略区间收益|买持区间收益|策略局部回撤|策略年化卡玛|买持年化卡玛|
|---|---:|---:|---:|---:|---:|
{year_lines}

年度切片继承连续账户的资金和持仓，收益不年化，卡玛分子按实际交易日年化；2026 YTD仅截至10月30日。局部回撤含窗口开头净值，另在原分析保留继承历史高点的回撤，不冒充重新投入本金的独立回测。

252实际交易日、步长21的34个窗口中，15个卡玛低于同窗买持，最长连续11个重叠窗口；超额卡玛Q10为-4.696830。最差相对窗口2025-05-08至2026-05-08，策略卡玛11.916、买持26.322，并非策略绝对亏损。最后一个固定步长窗口截至2026-10-08，其后16个交易日仍计入全期和年度，但不追加任意尾窗。重叠窗口不是独立市场样本。

前两年策略区间收益仅4.40%、8.30%，高收益主要发生于2025及2026 YTD；全期结果不能说明各时期都保有相对优势。具体分段、连续落后起止与逐窗明细见[时间分析](../../materials/c9380_stage4_completion/time_analysis.json)。

## 收益集中性与成对区间

95个闭合周期为47盈48亏。最大盈利周期占全部正盈利周期净利润9.04%，前5占38.57%；这5个均在2026年，金额贡献受复投后资本规模影响。分母为所有正盈利周期净利润416267.04美元，不是亏损抵消后的净利润。截止没有未闭合持仓；闭合净利润316937.11美元与财富净增一致。未删除交易重跑，不作反事实盈利承诺。

按同日期成对stationary bootstrap，10000次、平均块长21日、seed9380：策略减买持净年化差点估计-66.55个百分点，95%区间[-229.33,18.11]个百分点；日末卡玛差点估计3.346036，95%区间[-3.089264,5.613704]。区间跨零，相对卡玛优势仍有明显不确定性。接口基于日末收益；本次日末与BAR_CLOSE原账回撤恰好相同，但重抽样不等于策略逐柱重放。区间未经研究选择偏差校正，不是未来盈利概率。

## 研究族选择偏差

盘点EX002—EX063全部997份正式账户、976个完整定义，包括失败者。两组真实上下文的区别是MU/SOXX后复权辅助输入；没有强行合并。当前可比群组821份账户、800个定义、961日，含700种不同日收益序列，无常数列；旧176份不同上下文账户仍保留在来源清单。重复定义只有在逐日收益及上下文精确相同后才合并，并保留全部别名；当前矩阵C9380列与EX064中心逐日收益及日历、语义精确匹配。

|公开统计诊断|结果|
|---|---:|
|Sharpe代理PBO，10块252拆分|97.2222%|
|DSR，原始821次口径|4.5288%|
|相关性有效试验次数|1.622277|
|DSR，有效次数口径|70.2615%|

PBO表示该固定群组按夏普选出的样本内优胜配置在伪样本外容易落后，C9380未在这些拆分中被选为夏普优胜者；不能把97.22%解释为C9380亏损概率或其净卡玛目标的真实过拟合概率。DSR也检验夏普，两种次数口径差异很大，不能只采用较好看的70.26%。公开账户无法穷尽未发表想法和自适应研究选择；同一开发池的拆分不会恢复独立性。详见[研究族报告](../../materials/c9380_stage4_completion/family_statistics.md)。

## 接口阻断及研究建议

SE公开assess_candidates已生成v8面板，RSCH核对其收益/回撤、79点、频率、集中性、滚动卡玛及年化差区间与独立分析一致。后续CalmarComparisonRequest在CommonNeighborhoodComparisonContract._scale_signature拒绝非连续实数轴，本次真实设计含beta_window整数、4个固定短周期整数及固定add_mode类别。因此未构造比较结果、未发布ASSESSMENT，也未切换目标或伪造参数类型。

紧凑面板只允许中心账本，而内嵌研究族矩阵要求所有族成员账本，故族统计通过独立公开接口完成并作为补充证据；SE内嵌族诊断仍保留FAMILY_RETURN_MATRIX_NOT_SUPPLIED，未被手工填成通过。这项内嵌限制不必与本次混合轴修复捆绑。

建议保留C9380作为已达标候选，保持参数，先切换DEV按[最小修复需求](../../materials/c9380_stage4_completion/dev_request.md)支持合法混合参数轴，再复用已保存请求、面板和83账户完成正式比较/交付；无需重跑账户或bootstrap。本轮不建议继续在同一开发池微调来追求更好统计结果。完成正式阶段四交付后，再由用户决定是否进入阶段五技术检验；冻结、生产及独立前瞻验证均未自动获准。

本轮研究分析目标完成，正式阶段四交付目标尚未达成。已发布原账户、EX064报告及研究资格不变；短周期时序风险和历史HFQ可得性假设继续保留。[SE面板](others/panel.json) · [实际阻断](others/comparison_blocker.json) · [RSCH核对](others/rsch_verification.json)。
'''
    (WORK/'report.md').write_text(report,encoding='utf-8',newline='\n')
    repo=RepositoryContext.discover(ROOT)
    context=create_research_context(repo,d.ResearchBatchRef('S018'),providers=ProviderConfig(bindings={},equity_bindings={}),
        execution_spec=execution_spec_from_dict(accounts['CENTER']['definition']['execution_spec']))
    exp=d.ExperimentRef('S018',WORK.name)
    request_ref=publish_evidence(context,d.MaterialEvidenceWrite(exp,'retained-assessment-request',
        (SCRATCH/'request.json').read_bytes(),'application/json','json'))
    save(OUT/'retained_request_ref.json',request_ref.to_dict())
    refs=[request_ref,d.EvidenceRef.from_dict(read(OLD/'report_ref.json')['report'])]
    refs.extend(d.EvidenceRef.from_dict(x) for x in read(OUT/'account_references.json'))
    paths=[p for folder in (WORK/'src',OUT,MATERIAL) for p in sorted(folder.glob('*'))
        if p.is_file() and p.suffix in ('.py','.json','.md') and p.name!='publication_receipt.json']
    for p in paths:
        mime={'.py':'text/x-python','.json':'application/json','.md':'text/markdown'}[p.suffix]
        prefix='material' if p.parent==MATERIAL else p.parent.name
        refs.append(publish_evidence(context,d.MaterialEvidenceWrite(exp,prefix+'-'+p.stem,p.read_bytes(),mime,p.suffix[1:])))
    ref=publish_evidence(context,d.ExperimentReportWrite(exp,sha256((WORK/'report.md').read_bytes()).hexdigest(),
        d.ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    artifacts=tuple(d.ExperimentArtifactRef(exp,p.relative_to(WORK).as_posix(),sha256(p.read_bytes()).hexdigest())
        for folder in (WORK/'src',OUT) for p in sorted(folder.glob('*')) if p.is_file())
    validation=validate_experiment(repo,d.ExperimentValidationRequest(exp,d.ExperimentValidationScope.REPORT_PUBLICATION,artifacts))
    save(OUT/'publication_receipt.json',{'report':ref.to_dict(),'validation':asdict(validation),
        'scope':'EX065 research report and materials only; formal ASSESSMENT remains blocked.',
        'new_account_replays':0,'formal_assessment_published':False,'publication_seconds':perf_counter()-begun})
    assert validation.status.value=='PASS',validation.issues
    print('REPORT_PUBLISHED',ref.sha256,'INTEGRITY',validation.status.value,'FORMAL_ASSESSMENT_BLOCKED',flush=True)


if __name__=='__main__':
    main()
