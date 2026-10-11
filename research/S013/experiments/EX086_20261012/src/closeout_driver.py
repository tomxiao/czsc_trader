"""EX086 full delivery, preserve positive gain evidence and adverse net results."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_payoff_driver as d


def run():
    exp,plan=d.stage()
    path,c=exp.resolve(ROOT),d.base.common()
    ctx=c.context(1)
    refs={**d.read(path/'protocols/method_references.json'),**d.read(path/'protocols/result_references.json'),
          'verification.json':d.read(path/'protocols/audit_reference.json')}
    s,audit=d.read(d.public(refs['statistics.json'])),d.read(d.public(refs['verification.json']))
    assert audit['status']=='PASS' and audit['new_annual_models']==s['new_annual_models']==24
    assert audit['new_accounts']==s['new_accounts']==0 and audit['EX084_controls']=='EXACT'
    assert audit['result_references']==d.read(path/'protocols/result_references.json')
    assert audit['plan_reference']==refs['plan.json'] and audit['schedules']==42
    definition=d.base.load('payoff_review_definition',d.WORK/'kernel.py')
    core=s['bootstrap']['summary']
    assert tuple(core)==definition.QUANTITIES and all(r['valid_replicates']==500 for r in core.values())
    assert core['original14_gain_mse_improvement']['ci95'][0]>0
    assert all(row['ci95'][0]<0<row['ci95'][1] for key,row in core.items() if key!='original14_gain_mse_improvement')
    judgment='保留原14项对盈利幅度的局部预测支持；当前条件赚亏幅度与旧盈利概率合成的净盈利机制没有足够经济支持，原时钟两下跌年均亏，停止当前合成表达，不选最优相位或补扫算法参数。'
    pct=lambda v:'不可得' if v is None else f'{100*v:.4f}%'
    names={'training_mean':'历史均值','confirmation_only':'原确认直接净收益','original14_joint':'原14直接净收益',
           'confirmation_probability_payoff':'确认概率＋固定幅度','original14_probability_payoff':'14概率＋固定幅度',
           'confirmation_conditional_payoff':'确认概率＋条件幅度','original14_conditional_payoff':'14概率＋条件幅度'}
    report=f'''# EX086：容易赚钱是否也意味着赚得多

{judgment}

通俗说，胜率超过一半仍可能亏：赚时很少，亏时很大就不行。本轮保持EX084预测的赚钱概率，把“赚时预计赚多少、亏时预计亏多少”分别按当时价量信息预测，再组合为净期望。原14项确实包含一些盈利幅度信息，但当前概率、赚幅和亏幅组合后，依然没有解决下跌年份赚钱的问题。

## 研究依据与历史重复核对

原EX084的14项盈利概率映射相对直接净收益MSE改善约1.9997%，条件性区间为正，却选中净均值负；确认概率2023有有限支持而2022失败。旧映射假设同一年度所有状态的平均赚幅/亏幅相同，尚不能排除“胜率看起来好，但盈亏金额不合适”。EX085近期成熟状态没有解决净盈利，且明确未条件化赚亏幅度。本轮补检这个有明确区别的职责，不移动概率阈值。

已核对EX064的跳空修复/高开回吐、EX019/020上涨价格限制及原价量观察，跳空路线已有反证，不重复。条件幅度不是新增外部市场信息，只是原14项的预测职责拆分；同开发池反复使用，未宣称独立样本或封存验证。

## 事前固定方法及因果边界

仅原510500.SH已见开发池1635个T（2020-01-02至2026-09-29）、原14项及四日净标签Open[T+5]/Open[T+1]×.999/1.001−1。原HFQ锚点、无现金分红叠加、原资金费用整手/固定1%执行合同、只做多及四项经济硬门保持。原生完整账户交易1636日，不把组件标签轴改成频率分母。

盈利事件y>0；非盈利y<=0，零值不丢。赚幅目标y、亏幅目标−y。每年严格同EX084的成熟训练：2020<=信号年份<本测试年，目标结束严格早于本年首T，原14完整、目标有限，至少40且两组各至少20。共同原训练的ECDF中点秩−.5作坐标，分组后不重新标定秩；确认单列用原第8列，14项用全部原列。2020无预测，尾部缺未来标签仍保留特征预测，不用未来测试年数量决定当时预测。

12个EX084年度盈利概率模型和五类旧净预测逐字节认证、数值精确复用，不重新拟合。仅两信息族各自赚幅/亏幅，最多4×6=24新模型。训练日期逐条匹配EX084，不是EX085因状态暖启动而少5行的支持。

幅度均值采用exp(eta)，eta=截距＋价量秩×系数。固定最小化sum[eta＋m×exp(−eta)]＋5×sum[斜率²]；截距不惩罚，斜率L2=10，未优化。条件期望下，这个准则在exp(eta)=E[m|x]取最小，因此预测算术条件均值；不是先回归log(m)后把几何均值冒充算术均值。正均值的log连接可见[statsmodels原始文档](https://www.statsmodels.org/stable/generated/statsmodels.genmod.families.family.Gamma.html)。该引用仅为方法依据，不是ETF盈利证据；实际准则允许m=0，不宣称零幅度服从Gamma密度或已检验真实分布。

固定Newton最多100步、Armijo最多40次、最大梯度<=1e−10。不收敛、非有限、全零幅度组显式拒绝，不填epsilon、不截断、不兜底。所有24模型实际4–5步收敛；训练非盈利中实际零净标签0个，零边界已合成检验。新净期望保持原概率p，采用p×G(x)−(1−p)×L(x)，严格>0才选；不扫期限、算法、alpha、概率阈值或相位。

最强反证：原14直接净均值/旧概率映射未提供稳定净盈利；拆组后更少样本、更受大涨大跌影响；错误概率会抵消幅度信息。合成9类检查、4类显式拒绝通过；独立标量Newton、成熟训练、全部42时钟、5000个重抽样量复算PASS。实际统计1次，24新拟合，0账户、0provider、0新增市场数据。

## 十项固定增量诊断

共同成熟预测1388个T，可预测1392个T。误差改善正值表示下降，负值表示恶化。500次原1635T轴重叠40日块seed13，固定预测不重拟合；至少20样本、至少400有效、LINEAR95%区间，全部500有效。条件性区间未经研究历史和多重比较校正，不是新硬门。选中均值差为百分点，不是账户年化差。

|数量|点估计|条件性95%区间|
|---|---:|---:|
'''
    for key,row in core.items():
        report+=f"|{key}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report+='''
原14赚幅MSE下降6.0202%，区间[1.0647%,11.5083%]，五个不重叠相位改善均正，这是保留的局部支持。它是在真实结果盈利子集上的幅度职责检验，不能在T知道哪笔将盈利，也不能直接当成买入资格。原14亏幅约改善0.8592%但区间跨零，合成净MSE反而恶化约0.6934%。确认族净MSE微改善约0.3902%也跨零。其余九项区间均跨零，不能把某个统计诊断当账户收益结论。

## 全部年份和相位的幅度诊断

以下为相对固定年度幅度及固定幅度净期望的MSE改善，不是年度净收益。

|组|14赚幅|14亏幅|14合成净期望|确认合成净期望|
|---|---:|---:|---:|---:|
'''
    for key,row in s['conditional_quality'].items():
        report+=f"|{key}|"+'|'.join(pct(row[k]) for k in ('original14_gain_mse_improvement','original14_loss_mse_improvement','original14_net_mse_improvement_vs_fixed','confirmation_net_mse_improvement_vs_fixed'))+'|\n'
    report+='''
原14赚幅支持不是每年一致：2022与2026分别恶化约8.51%、17.10%；2022亏幅也恶化约18.29%。保留所有反证，不把全窗显著当下跌年有效。

## 重叠正净预测的经济余量

四日扣费OPEN价格代理，可重叠，非账户。

|表达|正预测数|成熟数|平均净代理|实际盈利比例|
|---|---:|---:|---:|---:|
'''
    for name,row in s['panels']['all'].items():
        report+=f"|{names[name]}|{row['positive_forecasts']}|{row['mature_positive']}|{pct(row['positive_mean'])}|{pct(row['hit_rate'])}|\n"
    report+='''
确认条件幅度选648个成熟机会，均值+0.0987%，较旧固定幅度−0.0315%改善0.1302个百分点，但仍低于原确认直接净预测+0.1212%。14条件幅度选692个，均值−0.0150%，较旧−0.0214%只有微小改善。选中次数相同不代表相同日期、风险或账户交易。

|年份|确认固定幅度 数量/均值|确认条件幅度 数量/均值|14固定幅度 数量/均值|14条件幅度 数量/均值|
|---|---:|---:|---:|---:|
'''
    for year in range(2020,2027):
        cells=[]
        for name in (definition.MODELS[3],definition.MODELS[5],definition.MODELS[4],definition.MODELS[6]):
            row=s['panels']['year_'+str(year)][name]
            cells.append(f"{row['mature_positive']} / {pct(row['positive_mean'])}")
        report+=f'|{year}|'+ '|'.join(cells)+'|\n'
    report+='''
确认条件幅度2022仍−0.2346%，2023+0.1910%但低于旧固定幅度+0.6545%；2024新增机会稀释原均值，2026与旧表达完全相同仍负。14条件幅度2023从正变负，2022/2026均负。平均盈利幅度信息不足以自然解决概率、亏幅与入场时机。

## 全部42个入场时钟及年度复合代理

精确复用EX083原空仓贪心＋i%5五组，固定四日期限/冷却规则，无年度重置；不是等笔数/等风险比较，非32标准扰动，不选赢家相位。复合代理按入场年归组，跨年按入场年归因，不是连续账户自然年收益或回撤。省略原生限价未成交、整手资金、账户路径和最终浮盈亏。

|表达/时钟|成熟数|全窗复合|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    clock_summary={}
    for name,rows in s['schedules'].items():
        for clock,row in rows.items():
            a=row['panels']['all']
            report+=f"|{names[name]} / {clock}|{a['mature']}|{pct(a['compound_net_proxy'])}|"+'|'.join(pct(row['panels']['year_'+str(y)]['compound_net_proxy']) for y in range(2020,2027))+'|\n'
        if name in definition.MODELS[5:]:
            values=[r['panels']['all']['compound_net_proxy'] for r in rows.values()]
            clock_summary[name]={'full_min':min(values),'full_max':max(values),
                'positive_2022':sum(r['panels']['year_2022']['compound_net_proxy']>0 for r in rows.values()),
                'both_down_years_positive':sum(r['panels']['year_2022']['compound_net_proxy']>0 and r['panels']['year_2023']['compound_net_proxy']>0 for r in rows.values())}
    report+='''
确认新表达原贪心全窗−4.42%，2022−29.34%、2023−1.85%，较旧贪心+60.08%明显退化；14新表达原贪心全窗+12.86%较旧−4.33%改善，但2022−15.98%、2023−7.24%。有利和不利都保留，不仅根据重叠均值决定账户支持。

确认phase_3全窗+72.94%，2022+0.9063%、2023+3.1149%、2026+2.6381%，是最强有利反证；另phase_1全窗+60.45%、2022正但2023微负。确认六时钟只有一组两个下跌年均正，全窗范围−26.94%至+72.94%。14六时钟2022全部亏损。不能事后选phase_3为新策略，也不把这些代理通过当原生硬门通过。

## 训练与交付

|测试年|训练数|盈利数|非盈利数|零净标签数|最大迭代|最大梯度|
|---|---:|---:|---:|---:|---:|---:|
'''
    for year,row in s['fit_years'].items():
        maxiter=max(q['iterations'] for q in row['models'].values())
        maxgrad=max(q['max_abs_gradient'] for q in row['models'].values())
        report+=f"|{year}|{row['train_n']}|{row['win_n']}|{row['nonpositive_n']}|{row['zero_net_n']}|{maxiter}|{maxgrad:.3e}|\n"
    report+='''
原四项硬门保持，收益Q10、回撤Q90、32点逐项/联合达标率、双费结果均未由本轮取得，不可得而非零/通过。没有新完整账户或候选。总体目标未达成。

保留原14盈利幅度作为有限信息组件；停止当前同时条件化赚幅/亏幅再与旧概率合成的固定表达。下一步有依据的最小对照是复用现成预测，拆开盈利概率、赚幅、亏幅的作用，完整列出固定/条件组合，查明有用赚幅是否被其他项抵消。该对照尚未执行，不新增拟合、不挑组/调参数，不把单一正区间当经济硬门；只有经济支持一致才进入原生账户。

追加额度已完成8/10（EX079–EX086），剩余EX087/EX088两轮，用完暂停，不启动EX089。正式报告完整副本保存本实验others/report.md，字节数、逐字节及SHA256核对。
'''
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'objective_achieved':False,
        'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,'new_accounts':0,'new_annual_models':24,
        'reused_probability_models':12,'append_account':False,'clock_summary':clock_summary,
        'limited_supported_responsibility':'Original14 positive-outcome amplitude MSE +6.0202%; conditional CI positive, five phases positive;2022/2026 worse;not profit gate',
        'favorable_counterevidence':'Confirmation selected mean turns positive;original14 greedy proxy improves;confirmation phase3 both down years positive;all retained',
        'next_action':'Minimal decomposition of frozen probability/gain/loss legs before any new account, no refit/parameter/clock selection',
        'evidence_references':{k:refs[k] for k in ('plan.json','statistics.json','verification.json')},'report_markdown':report}
    d.write(d.OUT/'root_review.json',review)
    refs['root_review.json']=d.put(ctx,exp,d.OUT/'root_review.json')
    refs['closeout_driver.py']=d.put(ctx,exp,Path(__file__))
    budget={'status':'ROUND8_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT','authorization_reference':plan['continuation_budget_reference'],
        'maximum_additional_experiments':10,'started':8,'completed':8,'remaining':2,'completed_experiment':exp.to_dict(),
        'next_allowed':'EX087','last_allowed':'EX088','pause_after_EX088':True,'new_accounts_this_round':0,'objective_achieved':False}
    d.write(d.OUT/'budget_receipt.json',budget)
    refs['budget_receipt.json']=d.put(ctx,exp,d.OUT/'budget_receipt.json')
    for value in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference']):
        d.public(value)
    evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference'])))
    tests=tuple(m.ComponentTestResult('CONDITIONAL-PAYOFF-'+name,exp.experiment_id,EvidenceRef.from_dict(refs['plan.json']),status,explanation,
        tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json','verification.json','root_review.json')))
        for name,status,explanation in (
            ('ORIGINAL14-GAIN',m.ComponentTestStatus.SUPPORTED,'限定盈利结果子集的幅度预测MSE改善6.02%，区间正、五相位正；2022/2026更差，不代表可识别未来盈利或账户达标'),
            ('ORIGINAL14-LOSS',m.ComponentTestStatus.INEFFECTIVE,'亏幅微改善但区间零交叉，2022恶化，尚无稳定风险职责支持'),
            ('CONFIRMATION-NET',m.ComponentTestStatus.INEFFECTIVE,'重叠均值转正及phase3有利完整保留，原贪心下跌年及全窗退化，时钟不稳'),
            ('ORIGINAL14-NET',m.ComponentTestStatus.INEFFECTIVE,'有盈利幅度信息但净MSE恶化、选中均值负，原贪心局部改善仍两下跌年亏损')))
    entry=m.ComponentEntry('CONDITIONAL-H4-PAYOFF-MEANS',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-conditional-payoff/kernel.py']),'forecasts'),
        '原确认/14信息的盈利和非盈利幅度预测，与冻结旧盈利概率组合净期望',
        '原h4扣费HFQ OPEN价格净标签，条件正/非正幅度职责，非原生账户','h4固定，年度成熟扩展训练，alpha10固定',
        '原概率与固定幅度对照精确复用EX084；仅幅度新拟合24次，条件幅度及合成经济职责分别判断',
        '只用测试年之前且结束严格早于首T的成熟训练；当前T原特征；预测尾部不需要未来标签',
        '原510500开发池HFQ锚/无现金分红叠加/资金费用整手/1%合同，0账户/provider',
        '条件盈利幅度支持不等于T已知将盈利；分组小样本/极端行情/选择偏差；完整代理不替代硬门自检',judgment,tests)
    report+='\n\n正式证据：\n\n'+''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    receipt=assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.COMPONENTS,20,tuple(m.DeliveryReference.from_dict(v) for v in plan['predecessors'])),
        m.DeliveryContent(m.ComponentPanel((entry,),judgment),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    d.write(path/'protocols/delivery_reference.json',receipt.reference.to_dict())
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    d.write(path/'protocols/delivery_validation.json',validation.to_dict())
    d.write(path/'protocols/closeout_references.json',refs)
    if validation.status.value!='PASS':
        raise RuntimeError(validation.to_dict())
    formal,copy=ROOT/'research/S013/deliveries/COMPONENTS/20/report.md',path/'others/report.md'
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
    print({'experiment':exp.experiment_id,'COMPONENTS':20,'FULL':'PASS','report_copy':'EXACT','completed':8,'remaining':2})


if __name__=='__main__':
    run()
