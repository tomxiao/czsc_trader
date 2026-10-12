"""EX092 fixed co-down hypothesis negative result, complete evidence delivery."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402
OUT=ROOT/'.tmp/s013-new-goal/result092'


def pct(value):
    return '不可得' if value is None else f'{100*value:.4f}%'


def main():
    exp,path,plan,refs=g.stage(92)
    result,audit=(g.read(OUT/name) for name in ('statistics.json','verification.json'))
    assert audit['status']=='PASS' and result['new_models']==12
    assert result['fixed_hypothesis']=='negative' and result['partial']['value']>0
    assert result['bootstrap']['summary']['augmented_mse_improvement_vs_controls']['ci95'][1]<0
    judgment='固定20日共同下跌依赖未支持风险负向假说：全池及五相位控制后反而正向，预测误差恶化，正预测净均值为负。停止此固定入场风险表达，不翻向或改窗救援。'
    report=f'''# EX092：隔夜和日内一起下跌，能否识别不值得买的机会

{judgment}

通俗说，“夜里跌、白天也跌，往后买入更危险”并没有获得本轮支持。把各自跌幅和频率等旧信息控制后，整体关系反而朝相反方向；加入它的预测也更差。第四轮完成，总体稳健达标目标尚未达成。

## 问题、既有依据及最强反证

EX060测各自负能量，EX064测缺口修复/回吐，EX069测四日负幅支配；本轮检验逐日配对关系，区别于这些边际和修复表达，也区别于EX091同日下一bar量响应。它仍只是旧价格的新交互，不是独立数据或已有盈利发现。已有风险模型及过滤/提前退出失败是主要反证：风险过滤会排除盈利年反弹，20日状态高度重叠，当前开发池已反复研究。

事前唯一负向假说：a=max(−log(O/Cprev),0)，b=max(−log(C/O),0)；X=(mean20(ab)−mean20(a)*mean20(b))/sqrt(mean20(a²)*mean20(b²))，固定过去20完整交易日含T及真实前Close。无20支持则NA，任一负能量0仅X=NA，六边际仍保留；分子真实0保留X=0，跨年不重置。不更换窗口、翻号、选择h8或删控制救援。

## 新目标与事前设计

新版四门：净年化至少同期正buyhold的1.5倍、每自然年最大回撤严格更小、所有buyhold盈利年份合并每60交易日至少4真实闭合交易、每个buyhold亏损年真实连续账户收益严格为正；中心及标准32均须联合通过。年度最终盈亏只事后验收，不作为策略信号；全期频率只报告诊断。仅原S013510500开发池、HFQ固定锚、不另叠加现金分红，原100万元/整手100/单侧10bp/固定1%执行合同保持。

原1635T轴不删除。只复用1637个anchor+evaluation价格点，没有新增2019预热或训练；初20支持不足保留缺失。主标签为h4扣双边10bp的Open[T+5]/Open[T+1]*0.999/1.001−1，T+5OPEN成熟，未来尾部真值缺失仍保留当时预测。

固定27控制为原14、六边际mean_a/mean_b/rms_a/rms_b/freq_a/freq_b、EX061两端点、EX068四顺序/幅度、EX075同期量协方差。控制与增广同28有限支持，全年最终结果未用于挑训练。统计方法沿EX091原数学保持：年度2021..26，只训练2020起此前年度且标签成熟严格早于本年首T；train40、训练ECDF中点秩、ridge10截距未罚，不以未来测试数量/标签决定能否预测。

raw/partial秩相关及500次原T轴重叠40块seed13，20n/10残差自由度/400有效、LINEAR95%描述区间；4个预测数量和18全部入场时钟。固定预测/入场选择在重抽样中不重拟合，不按拼块重模拟时钟；不是标准32或独立封存检验，没有校正同池多重选择。没有新增硬门。

## 全池正反证

|关系|点估计|95%描述区间|样本|
|---|---:|---:|---:|
'''
    for name in ('raw','partial'):
        row=result[name]
        report+=f"|{name}|{row['value']}|{result[name+'_bootstrap']['ic95']}|{row['n']}|\n"
    report+='''
全池raw约+0.0866、partial约+0.0512，区间均含零；五个固定相位partial均正，和事前“更差净机会”的负向假说相反。2020/2021/2024部分年度负向是保留的局部支持，不能挑年份重新定义风险信号。

|固定数量|点估计|95%描述区间|有效次数|
|---|---:|---:|---:|
'''
    for key,row in result['bootstrap']['summary'].items():
        ci=row['ci95']
        report+=f"|{key}|{pct(row['value'])}|{('['+pct(ci[0])+', '+pct(ci[1])+']') if ci else '不可得'}|{row['valid_replicates']}|\n"
    report+='''
增广比controls误差改善−0.9296%，区间整段为恶化；比过去均值−5.9213%，同样恶化。新正预测选择的成熟净均值−0.0321%，相对controls还低−0.0045个百分点，两选择区间含零。不能把全池正描述翻译成可交易买入正信号，也不因统计区间另加用户否决门。

## 全年度及固定相位

|范围|raw|partial|partial样本/秩/自由度|比controls误差改善|新正选择均值|比controls选择差|
|---|---:|---:|---:|---:|---:|---:|
'''
    for key,row in result['panels'].items():
        r,q=row['partial'],row['quantities']
        report+=f"|{key}|{row['raw']['value']}|{r['value']}|{r['n']}/{r['design_rank']}/{r['residual_df']}|{pct(q['augmented_mse_improvement_vs_controls'])}|{pct(q['augmented_positive_mean'])}|{pct(q['augmented_positive_minus_controls'])}|\n"
    report+='''
## 成熟训练与核验

|测试年|成熟训练数|完整特征预测数|状态|
|---|---:|---:|---|
'''
    for row in result['fit_trace']:
        report+=f"|{row['year']}|{len(row['train_positions'])}|{len(row['test_positions'])}|{row['reason'] or 'AVAILABLE'}|\n"
    report+='''
主特征10类检查/12拒绝、480全部滑窗标量复算；独立特征9类/30拒绝；主统计8类/3拒绝；独立统计400合成覆盖2020..26所有12拟合/1000相关抽样/2000预测数量/18时钟均PASS。独立特征初次人工跨年样本历史19日不足，修正人工起始日期后PASS；仅合成构造修正，无真实科学规则变化。

真实公共原生账户与缓存严格匹配、HFQ O/C及原日历逐值一致、旧14/端点/顺序/同期量协方差和成熟标签核验通过；真实特征和全部trace独立log/fsum复算，独立ECDF、12全部ridge正规方程/预测、全部相关及4×500数量/18时钟核验PASS。实际研究一次、12模型、0提供者调用、0新账户。

## 全部18时钟及集中性

复用h4原贪心和全轴i%5五相位，退出优先同T不重入，不按年重置。不择年度或相位。价格复合按入场年归组，不能当连续账户收益、最大回撤或实际闭合交易；未涵盖限价未成交/整手现金/尾部持仓估值。

|表达/时钟|成熟数|全期复合|2020|2021|2022|2023|2024|2025|2026|最大约10%正机会贡献|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for name,clocks in result['schedules'].items():
        for clock,row in clocks.items():
            p=row['panels']
            report+=f"|{name}/{clock}|{p['all']['mature']}|{pct(p['all']['compound_net_proxy'])}|"+'|'.join(pct(p['year_'+str(y)]['compound_net_proxy']) for y in range(2020,2027))+f"|{pct(p['all']['top_positive_contribution'])}|\n"
    report+='''
原贪心controls全期−10.64%，加入X−13.09%；2022从−15.43%变−20.04%，2023从−9.68%减亏至−5.16%。后者及两个固定相位全期改善是有利反例，全部六时钟2022仍负；不能选择相位4的2023转正来宣称下跌年达标。

## 收口与下一步

停止本固定共同下跌入场风险表达，不反向改成买入、邻窗调整或与旧模型混合救援。结论限定于本表达，不能推广为所有隔夜风险或风险控制无用。下一方向转到TIME时钟与交易接受状态的职责分离：市场机会episode不由确认通过、实际信号入场或上次TIME退出重置；先证明独立及父规则关闭等价，再用一个完整原生中心检验，不能只做价格标签相关替代交易。

4/10轮完成，剩余6，实际新增账户0。中心新版四门、标准32逐项/联合达标率、收益Q10/回撤Q90及最新五项完整账户自检本轮不可得，不写0或通过。正式FULL和report精确副本只表示该轮证据完整，总体稳健目标尚未达成。
'''
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'new_models':12,'new_accounts':0,
        'objective_achieved':False,'native_followup_supported':False,
        'next_direction':'transaction-independent market episode TIME clock; one native centre, not sign/window rescue'}
    g.write(OUT/'root_review.json',review)
    ref=g.close_component(92,component_id='JOINT-OVERNIGHT-INTRADAY-NEGATIVE-DEPENDENCE20',entrypoint='forecasts',
        judgment=judgment,status=g.m.ComponentTestStatus.INEFFECTIVE,report=report,
        results={name:OUT/name for name in ('statistics.json','verification.json','features.csv','co_down_features.csv','forecasts.csv','availability.json','input_checks.json','root_review.json')}|{'closeout_driver.py':Path(__file__)})
    with (path/'src/co_down/closeout.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print({'experiment':exp.experiment_id,'COMPONENTS':ref.revision,'FULL':'PASS','report_copy':'EXACT','completed':4,'remaining':6})


if __name__=='__main__':
    main()
