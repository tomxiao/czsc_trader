"""EX085 root review and full matched-state component delivery with report copy."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_recent_state_driver as d


def run():
    exp,plan=d.stage()
    path,c=exp.resolve(ROOT),d.base.common()
    ctx=c.context(1)
    refs={**d.read(path/'protocols/method_references.json'),**d.read(path/'protocols/result_references.json'),
          'verification.json':d.read(path/'protocols/audit_reference.json')}
    s,audit=d.read(d.public(refs['statistics.json'])),d.read(d.public(refs['verification.json']))
    assert audit['status']=='PASS' and audit['new_annual_models']==s['new_annual_models']==24
    assert audit['new_accounts']==s['new_accounts']==0 and audit['state_cells']==3270 and audit['matched_training']
    assert audit['result_references']==d.read(path/'protocols/result_references.json') and audit['plan_reference']==refs['plan.json']
    kernel=d.base.load('recent_state_review_definition',d.WORK/'kernel.py')
    core=s['bootstrap']['summary']
    assert tuple(core)==kernel.QUANTITIES
    assert all(row['valid_replicates']==500 and row['ci95'][0]<0<row['ci95'][1] for row in core.values())
    assert core['state_brier_improvement_vs_original14']['value']>0 and core['state_return_mse_improvement_vs_original14']['value']<0
    assert core['state_payoff_positive_mean']['value']<0
    for model in (kernel.MODELS[2],kernel.MODELS[4]):
        assert all(r['panels']['year_2022']['compound_net_proxy']<0 for r in s['schedules'][model].values())
    judgment='近期20个已成熟四日机会的盈亏比例/均值，未提供足够的原14项之外后续净收益增量；概率误差小幅改善但区间含零，净预测及选中均值未改善。原时钟代理改善和2023部分有利结果保留，仍未解决下跌年份盈利。停止当前20窗口状态表达，不补扫窗口/期限/alpha或把代理替代原生账户。'
    pct=lambda v:'不可得' if v is None else f'{100*v:.4f}%'
    names={'training_mean':'匹配历史均值','original14_return':'匹配14项直接收益','original14_state_return':'14项＋近期状态直接收益',
           'original14_probability_payoff':'匹配14项概率映射','original14_state_probability_payoff':'14项＋近期状态概率映射'}
    report=f'''# EX085：近期已结束机会的盈亏能否补充当前状态

{judgment}

通俗说，过去几年平均还能赚钱，不等于现在适合买。上一轮2022的历史盈利比例和实际情况出现明显偏差，本轮把“最近已经结束的20个四日机会，有多少盈利、平均赚亏多少”加入原价量信息。它计算上确实能及时更新，但没有证明能改善后续净盈利选择；某些入场时钟的价格代理改善，仍没守住两个下跌年份。

## 因果边界和事前设计

仅原510500.SH已见开发池，原1635T、原14项、原后复权固定锚、无现金分红叠加，原资金费用/整手/1%执行合同和只做多、四项硬门保持。原四日净标签Open[T+5]/Open[T+1]×.999/1.001−1不变，没有新市场数据或2019标签扩展。

每个历史及当前T，只用结束日期不晚于T且净价格标签已知的旧机会，按原信号顺序取最后20个。结束日期等于T意味着当天OPEN已经知道，允许使用；当天新机会的未来标签不进入。当不足完整20个时状态缺失，不用短窗兜底。两项状态是严格正净比例（零归非盈利）和平均净收益，窗口20与原20尺度组件一致，未扫描最优窗口。

实际首个完整窗口在2020-02-13形成，所用20个原位置0–19，最大成熟日期等于该T。每T20个位置、可用性和最大成熟日期均保存，全部3270状态单元与窗口由独立实现复算。尾部未来标签不可得，仍可使用此前已经成熟的20个机会形成状态和预测。

对照与增广采用完全相同的16项共同完整行和成熟训练T。新增窗口让2020最初几行不可得，旧EX084样本不相同，故不能复用旧模型作为配对控制；本轮重新拟合匹配14项，历史结果保持不可变。不能把样本变化误称为新组件收益。

两种职责分别是原14 vs 原14＋两状态的直接净收益ridge，以及同两特征集的净盈利事件logistic。年度2021–2026四类模型共24次拟合，恒定历史均值/概率为计算对照。训练只用2020起、早于测试年、目标结束严格早于该年首T、16项共同完整的成熟样本，至少40且盈利/非盈利各20，无未来全年测试样本数门。原训练ECDF中点秩−0.5、固定ridge10、固定EX084logistic斜率L2=10/不惩罚截距/显式数值收敛保持，不扫描算法或阈值。

概率仍按同一成熟训练的平均正/非正净收益映射为净期望，只在>0时选择。本轮先检验状态信息，未更新或条件化盈亏幅度，不宣称这一定是最优映射。2020无预测，测试标签只用于事后评分或在确实成熟后成为状态输入。

最强事前反证：原14已有动量、波动、延续性和交易信息，近期状态可能重复这些信息；20个四日代理高度重叠，近期盈亏也可能反转。原均值、概率、日期表达没有解决硬门；同开发池已反复使用，不是封存验证。合成10类检查、3类输入拒绝及单类别无兜底检查通过；独立状态窗口、配对训练、标量ridge/Newton、30时钟和5000个重抽样量复算通过。实际统计1次，0账户、0provider、0新增市场数据。

## 全部十项固定增量诊断

共同成熟预测1388个T，可预测1392个T。正改善表示误差降低，负表示增加。共享完整1635T轴500次重叠40日块、seed13，固定预测不重拟合；原始/重抽样至少20、至少400有效才报LINEAR95%区间。全部500次有效，十项区间都跨零，未校正研究历史与多重比较。均值差采用百分点解释，不能当账户收益。

|固定数量|点估计|条件性95%区间|
|---|---:|---:|
'''
    for key,row in core.items():
        report+=f"|{key}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report+='''
概率Brier和logloss相对匹配14项小幅改善约0.2886%、0.2124%，但没有稳定增量；新概率表达仍不及恒定历史频率。直接/映射净收益MSE分别恶化约0.2597%、0.2321%。这些是诊断，不是新增经济否决门，不能由MSE直接断言账户必然更差。

## 正净期望机会的经济余量

允许信号重叠的四日净OPEN价格代理，非账户。

|表达|正预测数|成熟正预测数|平均净代理|实际盈利比例|
|---|---:|---:|---:|---:|
'''
    for name,row in s['panels']['all'].items():
        report+=f"|{names[name]}|{row['positive_forecasts']}|{row['mature_positive']}|{pct(row['positive_mean'])}|{pct(row['hit_rate'])}|\n"
    report+='''
增广直接收益选694个成熟机会，净均值约+0.0093%，非常薄且低于匹配控制的+0.0386%；增广概率映射选658个，均值约−0.0985%，也低于控制−0.0655%。提高一些命中比例并未带来更强的净收益余量。

## 全部年度结果

表内为成熟正预测数量/净代理均值；不足20时不可得，非自然年账户收益。

|年份|匹配14直接收益|＋状态直接收益|匹配14概率映射|＋状态概率映射|
|---|---:|---:|---:|---:|
'''
    for year in range(2020,2027):
        cells=[]
        for name in kernel.MODELS[1:]:
            row=s['panels']['year_'+str(year)][name]
            cells.append(f"{row['mature_positive']} / {pct(row['positive_mean'])}")
        report+=f'|{year}|'+ '|'.join(cells)+'|\n'
    report+='''
两种增广表达2022的机会均值仍明显为负。2023概率映射从控制约−0.0590%变为+0.0613%，选88个成熟机会，是有利线索；直接收益该年仍负。2024增广均值降低，2025概率映射略好，2026仍负，所有年份均完整保留。

## 匹配训练样本和后续概率校准

|测试年|匹配训练数|盈利/非盈利数|历史盈利比例|历史盈亏平衡概率|增广平均预测概率|实际盈利比例|
|---|---:|---:|---:|---:|---:|---:|
'''
    old=d.read(d.public(plan['input_references']['prior_statistics.json']))
    matching={}
    for year,row in s['fit_years'].items():
        p=row['payoffs']
        quality=s['probability_quality']['year_'+year]['original14_state_probability']
        matching[year]={'current_matched_train_n':row['train_n'],'EX084_train_n':old['fit_years'][year]['train_n'],
                        'same_rows_between_current_models':True}
        report+=f"|{year}|{row['train_n']}|{row['win_n']} / {row['nonpositive_n']}|{pct(p['win_fraction'])}|{pct(p['break_even_probability'])}|{pct(quality['mean_probability'])}|{pct(quality['observed_positive_fraction'])}|\n"
    report+='''
本轮2021训练214个，EX084为219个；以后各年同样少5个初期样本。两职责及增广/对照都使用相同的新支持，比较为配对信息增量，未重写旧结论。训练日期和共同支持逐条可复算。

## 全部入场时钟有利与不利结果

原贪心及i%5五组精确复用EX083冻结实现；不同组机会数/持仓不同，不当等笔数比较，不选赢家组，不替代标准32点自检。成熟代理按入场年份归组，跨年依入场年；不是连续账户自然年回报或回撤。

|表达/时钟|成熟数|全窗复合|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    summary={}
    for name in (kernel.MODELS[2],kernel.MODELS[4]):
        rows=s['schedules'][name]
        for clock,row in rows.items():
            a=row['panels']['all']
            report+=f"|{names[name]} / {clock}|{a['mature']}|{pct(a['compound_net_proxy'])}|"+'|'.join(pct(row['panels']['year_'+str(y)]['compound_net_proxy']) for y in range(2020,2027))+'|\n'
        values=[r['panels']['all']['compound_net_proxy'] for r in rows.values()]
        summary[name]={'full_min':min(values),'full_max':max(values),'positive_2022':sum(r['panels']['year_2022']['compound_net_proxy']>0 for r in rows.values()),
                       'positive_2023':sum(r['panels']['year_2023']['compound_net_proxy']>0 for r in rows.values())}
    report+='''
原贪心的两种增广全窗复合代理约+0.81%、+10.53%，优于匹配控制−11.27%、−16.77%，这是不能隐藏的有利反证。改善不能仅凭MSE较差否定；但二者原贪心2022/2023仍负，2022全部六种安排均负。概率映射phase_3全窗约+52.90%，仍2022亏损，不因一个好时钟就升级账户。

完整30时钟、所有年度、正盈利集中和事后删项记录均在正式statistics.json，报告未按组筛选策略。代理省略原生限价未成交、整手资金及最终浮盈亏，意图/代理不等于实际闭合交易，不能填写硬门或正式自检指标。

## 收口与下一步

本轮组合状态没有足够的原14项外净盈利增量，当前表达不升级为原生账户；概率小改善、2023部分支持和原时钟代理改善保留。不推断所有近期状态信息无效，也不扫描窗口、alpha、期限或阈值来救援这条固定表达。

原四项硬门、目标和数据边界保持。没有新完整账户及五项策略自检证明，收益Q10、回撤Q90、32点逐项/联合达标率及双费结果均不可得，不填0或写通过。总体目标未达成。

下一步先核对是否已有“隔夜跳空与当日日内修复”的条件关系检验；原14项包含两者各自信息，但条件组合不同于线性相加。只有表达与历史方案确有区别才启动剩余额度的新对照，继续完整报告已有价格/日内反证，不重复已失败多数票或等待路线。该下一方向尚未执行，不称新独立样本或有收益保证。

追加额度已完成7/10（EX079–EX085），剩余3轮，最后EX088；使用完毕暂停，不启动EX089。正式报告完整副本保存在本实验others/report.md，逐字节及SHA256校验。
'''
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'objective_achieved':False,
            'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,'new_accounts':0,'new_annual_models':24,
            'matched_training_counts':matching,'clock_summary':summary,'append_account':False,
            'favorable_counterevidence':'Small probability improvement;2023state probability selected mean positive; both greedy full proxies improve against matched controls; retained',
            'next_action':'Check duplicate historical gap/intraday-recovery conditional expression before any next experiment',
            'evidence_references':{k:refs[k] for k in ('plan.json','statistics.json','verification.json')},'report_markdown':report}
    d.write(d.OUT/'root_review.json',review)
    refs['root_review.json']=d.put(ctx,exp,d.OUT/'root_review.json')
    refs['closeout_driver.py']=d.put(ctx,exp,Path(__file__))
    budget={'status':'ROUND7_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT','authorization_reference':plan['continuation_budget_reference'],
            'maximum_additional_experiments':10,'started':7,'completed':7,'remaining':3,'completed_experiment':exp.to_dict(),
            'next_allowed':'EX086','last_allowed':'EX088','pause_after_EX088':True,'new_accounts_this_round':0,'objective_achieved':False}
    d.write(d.OUT/'budget_receipt.json',budget)
    refs['budget_receipt.json']=d.put(ctx,exp,d.OUT/'budget_receipt.json')
    for value in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference']):
        d.public(value)
    tests=tuple(m.ComponentTestResult('RECENT-STATE-'+name,exp.experiment_id,EvidenceRef.from_dict(refs['plan.json']),
          m.ComponentTestStatus.INEFFECTIVE,explanation,
          tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json','verification.json','root_review.json')))
          for name,explanation in (('NET-RETURN','直接净收益误差及选中均值未改善，原时钟代理小改善仍下跌年亏损，未获可执行支持'),
                                   ('PROBABILITY-PAYOFF','概率小幅改善无稳定区间，2023及原时钟有利反证保留，2022六时钟均负，净均值更差')))
    entry=m.ComponentEntry('CAUSAL20-MATURE-H4-PAYOFF-STATE',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-recent-payoff-state/kernel.py']),'states'),
        '近期完整20个已结束机会的盈利比例/净均值状态，匹配原14两职责增量',
        '原h4 HFQ netOPEN价格标签，成熟后才作特征，非原生账户','固定h4/成熟20机会，无扫描',
        '16项共同完整同训练支持，原14与14＋状态的ridge/logistic，概率映射历史盈亏',
        '每T只用label_end<=T成熟的过去20位置，当前未来target不进入，完整窗口缺失不兜底',
        '原510500开发池HFQ固定锚、无现金分红叠加、原费用资金/1%合同保持；0账户',
        '高度重叠机会、配对控制重拟合而非旧样本复用，已见选择偏差；代理不填硬门/五自检',judgment,tests)
    evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference'])))
    report+='\n\n正式证据：\n\n'+''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    receipt=assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.COMPONENTS,19,tuple(m.DeliveryReference.from_dict(v) for v in plan['predecessors'])),
        m.DeliveryContent(m.ComponentPanel((entry,),judgment),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    d.write(path/'protocols/delivery_reference.json',receipt.reference.to_dict())
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    d.write(path/'protocols/delivery_validation.json',validation.to_dict())
    d.write(path/'protocols/closeout_references.json',refs)
    if validation.status.value!='PASS':
        raise RuntimeError(validation.to_dict())
    formal,copy=ROOT/'research/S013/deliveries/COMPONENTS/19/report.md',path/'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert formal.read_bytes()==copy.read_bytes()
    assert formal.stat().st_size==copy.stat().st_size
    d.write(path/'protocols/report_copy_verification.json',{'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),
            'experiment_report':copy.relative_to(ROOT).as_posix(),'formal_sha256':d.digest(formal),'copy_sha256':d.digest(copy),
            'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,
            'exact_bytes':True,'human_instruction':'RSCH，请在后续的每个实验目录下保存一份report副本'})
    with (path/'src/closeout_driver.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'COMPONENTS':19,'FULL':'PASS','report_copy':'EXACT','completed':7,'remaining':3})


if __name__=='__main__':
    run()
