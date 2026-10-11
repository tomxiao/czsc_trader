"""EX087 full factorial delivery with positive gain and adverse loss evidence."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_legs_driver as d


def run():
    exp,plan=d.stage()
    path,c=exp.resolve(ROOT),d.base.common()
    ctx=c.context(1)
    refs={**d.read(path/'protocols/method_references.json'),**d.read(path/'protocols/result_references.json'),
          'verification.json':d.read(path/'protocols/audit_reference.json')}
    s,audit=d.read(d.public(refs['statistics.json'])),d.read(d.public(refs['verification.json']))
    assert audit['status']=='PASS' and audit['new_annual_models']==s['new_annual_models']==0
    assert audit['new_accounts']==s['new_accounts']==0 and audit['EX084_EX086_controls']=='EXACT'
    assert audit['result_references']==d.read(path/'protocols/result_references.json') and audit['plan_reference']==refs['plan.json']
    assert audit['schedules']==96 and audit['factorial_edges']==24 and audit['bootstrap_checks']==7000
    definition=d.base.load('legs_review_definition',d.WORK/'kernel.py')
    core=s['bootstrap']['summary']
    assert tuple(core)==definition.QUANTITIES and all(r['valid_replicates']==500 for r in core.values())
    assert core['original14_gain_given_probability_mean_difference']['ci95'][0]>0
    assert all(core[f'{family}_loss_given_probability_gain_mean_difference']['ci95'][1]<0 for family in definition.FAMILIES)
    forecasts=pd.read_csv(d.public(refs['forecasts.csv']),index_col='signal_date',float_precision='round_trip')
    distinct=[]
    for name in forecasts:
        values=forecasts[name].to_numpy()
        if not any(np.array_equal(values,old,equal_nan=True) for old in distinct):
            distinct.append(values)
    assert len(distinct)==15
    judgment='赚幅预测确有局部净选择增量，尤其原14概率背景加入赚幅改善；当前条件亏幅在两族抵消增量。固定概率＋赚幅仍没有稳健下跌年经济支持，不挑单个入场相位升级账户，保留赚幅职责并停止当前亏幅组合直接交易化。'
    pct=lambda value:'不可得' if value is None else f'{100*value:.4f}%'
    report=f'''# EX087：赚钱幅度的价值被哪一部分抵消

{judgment}

通俗说，本轮把三件事分开：这笔赚钱的概率、赚时赚多少、亏时亏多少。前两件结合确实能筛出平均表现更好的机会；把当前亏幅预测也加进来，却放进了更多不合适的机会，几乎抵消改善。但剩下“概率＋赚幅”也仍在原入场安排下亏掉2022和2023，尚未形成达标策略。

## 依据、事前设计与准确计数

EX086原14盈利幅度MSE改善约6.02%，条件性区间正、五相位点估计正，但全组合的净MSE和经济表现不稳。本轮检验组成作用，未把整体失败解释成所有信息无效，未选EX086好相位或改写旧结果。

仅原510500.SH开发池、1635T/原h4扣费HFQ OPEN标签，原成熟年度训练、原HFQ锚、无现金分红叠加，原资金费用整手/固定1%执行合同、只做多及原四项硬门保持。固定概率P0是本年之前成熟训练的盈利比例；固定G0/L0是同一训练平均正净收益/非正净亏损幅度。P1为EX084冻结的确认/原14盈利概率；G1/L1为EX086冻结的条件赚幅/亏幅均值，全部精确认证复用，0新拟合/0新增市场数据/0账户/provider。

每信息族保留全部三位P/G/L组合000..111，0=固定，1=条件预测。所有组合净期望p×G−(1−p)×L，严格>0才选；无算法、阈值、方向、期限或起点扫描。000精确复用training_mean；100精确复用EX084固定幅度净表达；111精确复用EX086条件双幅度净表达，先核对代数恒等再使用旧控制原数值，非失败兜底。

16组合坐标只有15不同净预测列，两族000完全相同，是共享对照，不称独立重复实验。本轮只新增10个代数组合列，0新模型/候选/账户。确认001与000的入场选择和时钟结果在实际池相同，分数列不同也不代表新的交易信息。全部共享1392个可预测T/1388成熟T，2020无预测、尾部缺truth仍有已知特征预测，未来标签不改变本轮任何预测。

完整报告24条仅改变一项、其他两项相同的配对边及全年度/五相位；不把背景当独立样本。14项主诊断在实际分析前固定。最强反证：2022/2026盈利幅度预测原已更差；条件于盈利子集的幅度不能识别未来是否盈利；固定历史概率也可能漏掉变化；重叠均值改善可能只是被大涨和入场时钟影响。本池长期重复开发，未经独立封存验证。

7类合成检查、8类显式拒绝通过；代数、控制恒等、零期望不入场、前缀不变、未来标签不影响预测、全部24边/96时钟/7000个重抽样量由独立标量实现复算PASS。实际统计1次，0新拟合。

## 十四项固定增量诊断

共享原1635T轴500次重叠40日块seed13，预测固定不重拟合；样本至少20、至少400有效、LINEAR95%区间，全部500有效。误差改善正值表示下降；选中均值差为百分点，非账户年化差。区间没有校正研究历史和多重比较，非未来成功率或新增经济硬门。

|数量|点估计|条件性95%区间|
|---|---:|---:|
'''
    for key,row in core.items():
        report+=f"|{key}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report+='''
原14在旧概率背景加入赚幅（100→110），选中均值改善+0.1825个百分点，区间[+0.0185,+0.3644]个百分点。之后再加入亏幅（110→111），减少−0.1761个百分点，区间[−0.3050,−0.0583]；确认族相同亏幅添加也减少−0.0428个百分点，区间[−0.0867,−0.0070]。这是有方向的反证，不能继续把当前条件亏幅当“风险控制必然有用”。

确认单独加入赚幅（000→010）全标签净MSE改善0.7158%，条件性区间[0.0470%,1.5957%]，也属于保留的有限信息支持。原14概率加入已有赚幅（010→110）净MSE约恶化0.8108%，但区间跨零，不据此宣布所有盈利概率无用。其余主要区间跨零，指标本身不代替交易经济要求。

## 全部16组合的重叠净机会

允许重叠的四日扣费OPEN价格代理，非账户。

|表达(P/G/L)|正预测数|成熟数|平均净代理|实际盈利比例|
|---|---:|---:|---:|---:|
'''
    for name,row in s['panels']['all'].items():
        report+=f"|{name}|{row['positive_forecasts']}|{row['mature_positive']}|{pct(row['positive_mean'])}|{pct(row['hit_rate'])}|\n"
    report+='''
两族概率＋赚幅（110）都选627个成熟机会，日期并不相同，均值分别+0.1415%、+0.1611%。原14三项都条件化（111）增到692个机会，却变为−0.0150%；当前亏幅不是简单把更高风险全部筛掉，也可能通过低估亏损幅度放进不合适的机会。

单独条件赚幅（010）的确认/原14均值为+0.1129%、+0.1652%，各556/555个成熟机会；这些为有利线索。只条件亏幅（001）确认选择与固定历史均值相同、原14均值−0.2548%，不能以“预测更细”假定有经济价值。

## 全部24条单项替换边

同一背景只切换一项，净MSE和选中均值分别核对；选中样本会变，不当相同交易净利润之差。全部年份/相位配对边在正式statistics.json。

|配对边|净MSE改善|选中净均值差(百分点)|
|---|---:|---:|
'''
    for key,row in s['factorial_edges']['all'].items():
        report+=f"|{key}|{pct(row['mse_improvement'])}|{pct(row['selected_mean_difference'])}|\n"
    report+='''
这些是统计模型比较。不同腿共同影响净期望过零、机会数量、进入账户后的资金和持有冲突，不把配对均值差相加当真实利润归因。

## 全部年度重叠机会

每格为成熟正预测数量/平均净代理；不足20时均值不可得，0个机会不伪装为零收益。2023原14单独赚幅只有6个，保留小样本事实。
'''
    for family in definition.FAMILIES:
        report+=f'\n### {family}\n\n|年份|'+ '|'.join(definition.BITS)+'|\n|---|'+ '|'.join(['---:']*8)+'|\n'
        for year in range(2020,2027):
            cells=[]
            for bits in definition.BITS:
                row=s['panels']['year_'+str(year)][family+'_'+bits]
                cells.append(f"{row['mature_positive']} / {pct(row['positive_mean'])}")
            report+=f'|{year}|'+ '|'.join(cells)+'|\n'
    report+='''
2022所有16组合选中净均值都负。110确认/原14分别−0.1621%、−0.2988%，比各自100有改善但仍负；2023两者为+0.2061%、+0.3639%；2026仍负。不能用全窗正均值替代每个下跌年份盈利要求，也不能仅凭代理均值判实际账户必然失败。

## 全部96入场时钟及年度复合代理

原贪心（空仓先遇到正预测即入场）和i%5五组精确复用EX083；期限/冷却不变，不年度重置、不选赢家。机会数量、持仓和风险不同，非等笔数比较，非32标准扰动。成熟代理按入场年归组，跨年依入场年，不是连续账户的自然年收益/回撤；不含原生限价、整手、账户资金和最终浮盈亏。

|表达/时钟|成熟数|全窗复合|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    clock_summary={}
    for name,rows in s['schedules'].items():
        for clock,row in rows.items():
            a=row['panels']['all']
            report+=f"|{name} / {clock}|{a['mature']}|{pct(a['compound_net_proxy'])}|"+'|'.join(pct(row['panels']['year_'+str(y)]['compound_net_proxy']) for y in range(2020,2027))+'|\n'
        values=[r['panels']['all']['compound_net_proxy'] for r in rows.values()]
        clock_summary[name]={'full_min':min(values),'full_max':max(values),'both_down_years_positive':sum(
            all(r['panels']['year_'+str(year)]['compound_net_proxy'] is not None and r['panels']['year_'+str(year)]['compound_net_proxy']>0 for year in (2022,2023)) for r in rows.values())}
    report+='''
概率＋赚幅110原贪心：确认全窗+29.07%、2022−5.31%、2023−1.85%；原14全窗+15.67%、2022−17.14%、2023−2.78%。单独赚幅010原贪心2022也负。所有16组合原贪心2022都负，当前拆项没有得到一致经济支持。

最强有利反证是110的phase_1：确认2022+3.6694%、2023+0.7140%，原142022+2.5798%、2023+8.8567%，各自全窗+63.47%、+72.72%。但各族只有1/6时钟两个下跌年都正，其他安排仍亏；两者共享行情/相位，不当两次独立验证。不改选phase_1挽救策略，也不把本轮不升级账户解释成已证明账户不可能达标。

## 收口、历史容量和最后额度

保留原14赚幅带来的有限净选择增量、确认赚幅的净MSE增量；停止当前条件亏幅及全部固定组合直接交易化。统计错误、入场时钟、持有冲突仍妨碍稳定经济收益，某个配对区间正不能当新硬门，亏幅配对负也不一般化为所有风险信息无用。

原EX066已用未来信息计算正机会容量/最优增长和至少110笔约束，在放宽开盘成交假设下机会有供给；那不是可执行策略。本轮未重复该oracle，也不能靠再算理想上界增加可交易证据。

最后一轮先核对历史“等待/确认改善”是否覆盖了当前净预测强度与入场冲突的关系；只有有明确新增问题才设计验证，不扫相位或复做已失败等待。原14的110贪心选中均值约+0.1158%，被持仓占用的其他正预测约+0.1813%；确认110却相反（约+0.1789% vs +0.1267%）。这提示不能笼统假定“被错过的都更好”，须分别核对因果可得的强度和竞争解释。该下一检验尚未执行，不承诺仅改调度就能改善。

本轮0新账户、0候选及五项自检；收益Q10、回撤Q90、32点逐项/联合达标率、双费结果不可得，不填0或通过。原四项硬门、参数抗扰动追求和总体目标保持，总体未达成。

追加额度已完成9/10（EX079–EX087），仅余EX088；用完暂停，不启动EX089。正式report完整副本保存本实验others/report.md，字节数/逐字节/SHA256核对。
'''
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'objective_achieved':False,'new_annual_models':0,
        'new_accounts':0,'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,'append_account':False,
        'clock_summary':clock_summary,'limited_supported_responsibilities':['original14 gain given probability improves selected net mean','confirmation gain only improves netMSE'],
        'adverse_leg':'Both families conditional loss after probability+gain reduces selected mean; conditional CIs negative',
        'favorable_counterevidence':'Two110 phase1 have both down years positive; exactly one of six each;not independent samples;retained',
        'next_action':'Check duplicate history and causal forecast-strength vs entry conflicts before last experiment; no phase selection or repeated oracle',
        'evidence_references':{k:refs[k] for k in ('plan.json','statistics.json','verification.json')},'report_markdown':report}
    d.write(d.OUT/'root_review.json',review)
    refs['root_review.json']=d.put(ctx,exp,d.OUT/'root_review.json')
    refs['closeout_driver.py']=d.put(ctx,exp,Path(__file__))
    budget={'status':'ROUND9_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT','authorization_reference':plan['continuation_budget_reference'],
        'maximum_additional_experiments':10,'started':9,'completed':9,'remaining':1,'completed_experiment':exp.to_dict(),
        'next_allowed':'EX088','last_allowed':'EX088','pause_after_EX088':True,'new_accounts_this_round':0,'objective_achieved':False}
    d.write(d.OUT/'budget_receipt.json',budget)
    refs['budget_receipt.json']=d.put(ctx,exp,d.OUT/'budget_receipt.json')
    for value in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference']):
        d.public(value)
    evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference'])))
    tests=tuple(m.ComponentTestResult('PAYOFF-LEG-'+name,exp.experiment_id,EvidenceRef.from_dict(refs['plan.json']),status,explanation,
        tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json','verification.json','root_review.json')))
        for name,status,explanation in (
            ('ORIGINAL14-GAIN',m.ComponentTestStatus.SUPPORTED,'给定旧概率加入赚幅，选中净均值改善0.1825个百分点且条件性区间正；原贪心下跌年仍负，仅信息职责支持'),
            ('CONFIRMATION-GAIN',m.ComponentTestStatus.SUPPORTED,'固定历史概率下加入赚幅净MSE改善0.7158%且条件性区间正；不是经济硬门'),
            ('CONDITIONAL-LOSS',m.ComponentTestStatus.INEFFECTIVE,'在两族概率+赚幅背景，条件亏幅抵消选中净均值改善，配对区间负；未获风险职责支持'),
            ('ENTRY-EXPRESSION',m.ComponentTestStatus.INEFFECTIVE,'原贪心2022全部亏损，phase1局部支持完整保留，仅1/6同年均正，未得稳健交易支持')))
    entry=m.ComponentEntry('FROZEN-H4-PROBABILITY-GAIN-LOSS-LEGS',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-payoff-legs/kernel.py']),'combine'),
        '冻结概率/赚幅/亏幅的匹配固定和条件组合归因，保留信息与交易职责区分',
        '原h4扣费HFQ OPEN净标签，净选择增量和误差职责，非原生账户','固定h4/已冻结成熟年度预测，0新拟合',
        '每族全部8P/G/L组合、24单腿配对边，共享对照显式重复计数，全部年度/五相位/96时钟',
        '只复用已经认证的当T可得预测和严格成熟训练，不用未来truth改变新组合预测',
        '原510500开发池HFQ锚/无现金分红叠加/资金费用整手/1%合同，0账户/provider',
        '已见选择偏差、条件性区间、多重比较、共享000/同选择；代理不替代实际硬门或五自检',judgment,tests)
    report+='\n\n正式证据：\n\n'+''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    receipt=assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.COMPONENTS,21,tuple(m.DeliveryReference.from_dict(v) for v in plan['predecessors'])),
        m.DeliveryContent(m.ComponentPanel((entry,),judgment),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    d.write(path/'protocols/delivery_reference.json',receipt.reference.to_dict())
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    d.write(path/'protocols/delivery_validation.json',validation.to_dict())
    d.write(path/'protocols/closeout_references.json',refs)
    if validation.status.value!='PASS':
        raise RuntimeError(validation.to_dict())
    formal,copy=ROOT/'research/S013/deliveries/COMPONENTS/21/report.md',path/'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert formal.read_bytes()==copy.read_bytes() and formal.stat().st_size==copy.stat().st_size
    d.write(path/'protocols/report_copy_verification.json',{'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),
        'experiment_report':copy.relative_to(ROOT).as_posix(),'formal_sha256':d.digest(formal),'copy_sha256':d.digest(copy),
        'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,'exact_bytes':True,
        'human_instruction':'RSCH，请在后续的每个实验目录下保存一份report副本'})
    with (path/'src/closeout_driver.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'COMPONENTS':21,'FULL':'PASS','report_copy':'EXACT','completed':9,'remaining':1})


if __name__=='__main__':
    run()
