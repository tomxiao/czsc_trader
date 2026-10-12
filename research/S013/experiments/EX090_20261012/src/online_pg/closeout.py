"""EX090 scientific closeout after terminal independent audit; execute by root."""
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp/s013-new-goal'))
import governance as g  # noqa: E402

OUT = ROOT / '.tmp/s013-new-goal/result090'
FAMILIES = ('confirmation', 'original14')


def pct(value):
    return '不可得' if value is None else f'{100 * value:.4f}%'


def table_selected(result, groups):
    text = '|表达|' + '|'.join(groups) + '|\n|---|' + '|'.join('---:' for _ in groups) + '|\n'
    for name in result['panels']['all']:
        rows = [result['panels'][group][name] for group in groups]
        text += '|' + name + '|' + '|'.join(f"{row['mature_positive']}/{pct(row['positive_mean'])}" for row in rows) + '|\n'
    return text


def main():
    exp, path, plan, refs = g.stage(90)
    result = g.read(OUT / 'statistics.json')
    audit = g.read(OUT / 'verification.json')
    assert audit['status'] == 'PASS' and audit['bootstrap_records_checked'] == 6000
    assert audit['fits_verified'] == result['new_daily_models'] == 5568
    assert audit['fit_trace_rows'] == 3270 and audit['schedules'] == 48
    assert result['new_accounts'] == result['provider_calls'] == 0
    assert all(row['panels']['year_2022']['compound_net_proxy'] < 0 for row in result['schedules']['original14_online_pg'].values())
    assert result['schedules']['original14_online_pg']['greedy']['panels']['year_2023']['compound_net_proxy'] > 0
    assert all(result['bootstrap']['summary'][family + '_online_positive_minus_training_mean']['ci95'][0] > 0 for family in FAMILIES)

    judgment = ('逐T成熟标签扩展更新保留原14局部改善：重叠净选择均值提高、原贪心2022减亏且2023转正；'
                '但2022仍负、原14六个时钟2022全部负、2026变差，净预测未稳定胜过原年度模型。'
                '停止本固定dailyPG直接交易化，不扫窗口/正则/相位，不运行新账户；总体稳健达标目标未达成。')
    report = f'''# EX090：每天用已结束的机会更新预测，能否更好避开亏损

{judgment}

通俗说，这一轮没有等到新年才更新模型，而是在旧机会的结果真正出现后，逐日重估“赚钱概率”和“赚时赚多少”。原14项组合确有局部进步：原入场安排下2022损失明显减少，2023从负转正；但2022仍亏，2026变差，换入场安排也没有可靠地兼顾两个下跌年份。不能只凭更频繁更新就认为风险问题解决了。

## 目标、额度及执行边界

沿用用户批准的新版四门：整体净年化至少同口径正buyhold的1.5倍、每自然年回撤严格更小、全部buyhold盈利年份合并每60日至少4笔实际闭合交易、每个buyhold亏损年份实际净收益严格为正；中心及标准32个扰动点全部通过。全期频率只报告，年度最终涨跌只作事后验收，不能作为当时买卖输入。

本轮完成后为EX089–EX098授权额度的第2/10轮，剩余8轮；此前历史资格及原件保持。本轮0新完整账户、0新标准32点、0双费用账户，未追加数据或平台改动。原510500.SH开发池、2019预热、后复权固定锚且不叠加现金分红、100万元、整手100研究单位、单侧10bp、固定1%执行合同与只做多、不加杠杆保持。

公共全期频率字段不等于盈利年份合并频率；只有实际连续账户及真实退出日期才能核验新版频率门。下面的意图数量、价格代理收益不能冒充该硬门通过。

## 与旧路线的区别及最强事前反证

EX089固定20个成熟预测误差均值校准失败；本轮没有改它的窗口或阈值，而是保留EX087同一概率＋赚幅、固定训练损幅表达，检验估计更新时钟。EX084历史盈利结构未识别2022变化，EX086/87赚幅有局部支持，是本轮依据。

每日扩展训练仍然保留大量旧样本，并不会自动适应变化；没有新增市场信息。相邻四日标签重叠、少数大赚机会、资金占用时钟仍可能主导结果。原年度模型失效不能证明“只需每天更新”就会成功。开发池已反复研究，不能把此次自适应比较称为独立封存验证。

## 固定方法、成熟时点及独立核验

从2021开始，每个T只用2020起、原14项完整、训练信号严格早于当前T、真实h4标签有限且label_end<=T的扩展训练池。标签为Open[T+5]/Open[T+1]×0.999/1.001−1，直到T+5开盘才成熟；同日开盘已发生可用。不会根据未来测试年份的样本数决定可用性，不按年清空历史。

训练至少40条且严格盈利/非正各20条，零收益归非正；当前14项缺失为NA，不补短窗口。确认族只取第8号确认列，另一族取完整14列，但两族训练可用池均由原14共同完整信息确定。CDF中点秩由当T全部成熟训练拟合，再在赚幅拟合时取其中盈利行，不能在盈利子组重新拟合CDF。

概率精确调用冻结EX084 logistic，赚幅精确调用冻结EX086正幅度模型；原斜率惩罚10、100次Newton、40次Armijo、梯度阈值1e−10保持。损幅L是同一成熟池非正真实净收益的负均值，不恢复失败的条件亏幅模型。新净预测=P×G−(1−P)×L，不改变盈利事件分界，也不扫描窗口、正则、期限或交易门槛。

各族四表达：historical旧年度110预测原件；matched在当T日更新支持上复用旧预测；training_mean当T扩展真实训练均值；online_pg当T新概率与赚幅组合。旧年度模型不重拟合，所有historical时钟与EX087逐字段精确一致。

实际两族各1392个有效预测，第一次2021-01-04，成熟训练由220条扩展至1611条。两族每T各概率/赚幅两个拟合，共5568个实际模型；非正训练零收益数实际均为0，但零边界在合成中覆盖。两独立CPU进程、每进程BLAS线程1、族内T顺序执行，无串行降级。

14类合成检查/14类非法拒绝PASS；1244个合成拟合驻点核验PASS；400行双进程预测、800行trace与串行逐值相同，拆族合并及summarize等价。真实独立审计逐T标量枚举成熟池、bisect训练CDF，并从已保存系数重建全部5568拟合的概率/幅度/目标/梯度及净预测；没有重复优化拟合。3270个fit trace、48时钟/年度面板和6000个重抽样数量核验PASS。实际分析一次，0provider调用。

## 十二项事前固定诊断

原1635T轴500次重叠40日块、seed13；预测和完整轴入场选择固定，不在拼接块内重做时钟或模型。样本至少20、有效次数至少400，LINEAR95%描述区间。误差改善正表示更准，选择均值差为百分点；这些不是账户年化差、未来概率或新增硬门，区间未校正研究选择及多重比较。

|数量|点估计|95%描述区间|有效次数|
|---|---:|---:|---:|
'''
    for key, row in result['bootstrap']['summary'].items():
        interval = row['ci95']
        report += f"|{key}|{pct(row['value'])}|" + (f"[{pct(interval[0])}, {pct(interval[1])}]" if interval else '不可得') + f"|{row['valid_replicates']}|\n"
    report += '''
确认/原14净MSE相对年度matched分别恶化约0.0607%/0.3704%，区间都跨零，没有稳定更准；原14相对扩展历史均值也略差。全池正选择均值确认+0.1389%、原14+0.2311%，原14比年度matched+0.1611%提高0.0700个百分点，但该增量区间跨零。

真正有利证据保留：两族正选择均值都好于只用当T扩展历史均值选择，差约+0.4780/+0.5702个百分点，两区间下端都为正。竞争解释是这个简单training_mean对照自身选中均值为−0.3391%，明显较弱；胜过弱对照不等于胜过原年度PG或达标策略。不能把12项全部写成区间跨零，也不能把局部有利区间改作新硬门。

## 重叠机会的年度及五相位完整面板

每格为成熟正选择数/平均扣费价格标签。标签允许机会重叠，均值不是账户回报；少于20均值明确不可得，无机会不是零收益。

'''
    report += table_selected(result, ['all'] + ['year_' + str(year) for year in range(2020, 2027)])
    report += '\n全轴固定i%5后再筛选的五相位，不按年重置，不选择赢家：\n\n'
    report += table_selected(result, ['phase_' + str(k) for k in range(5)])
    report += '''
2022原14选中机会由162降至122，净均值从−0.2988%改善至−0.2111%，仍负；2023由54降至40，均值由+0.3639%增至+0.4672%。确认族2022均值从−0.1621%变为−0.2209%，是必须同时保留的反证。2026原14选中均值也略变差，不能只报告全年合并均值的改善。

## 同支持配对预测误差

三表达共同有限且真值成熟的样本比较；零控制误差的相对改善明确不可得，不补零。

|范围/族|配对数|matched MSE|training_mean MSE|online PG MSE|比matched改善|比training_mean改善|
|---|---:|---:|---:|---:|---:|---:|
'''
    for group, families in result['paired_prediction_errors'].items():
        for family, row in families.items():
            numeric = [row[name] for name in ('matched_mse', 'training_mean_mse', 'online_pg_mse')]
            report += f"|{group}/{family}|{row['paired_mature']}|" + '|'.join('不可得' if value is None else f'{value:.10g}' for value in numeric) + '|'
            report += pct(row['net_mse_improvement_vs_matched']) + '|' + pct(row['net_mse_improvement_vs_training_mean']) + '|\n'
    report += '''
## 全部48个入场时钟及年度复合代理

复用EX083原贪心及全轴i%5五组，固定h4退出优先/同T不重入，不按年重置。各时钟数量及占用不同，非等笔数或标准32点比较；以下年度按入场年归属，跨年按入场年计算，不等于连续账户自然年收益或回撤。未包含1%限价未成交、整手现金、真实退出或尾部持仓估值。

|表达/时钟|成熟数|全期复合|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for name, clocks in result['schedules'].items():
        for clock, row in clocks.items():
            panels = row['panels']
            report += f"|{name}/{clock}|{panels['all']['mature']}|{pct(panels['all']['compound_net_proxy'])}|" + '|'.join(pct(panels['year_' + str(year)]['compound_net_proxy']) for year in range(2020, 2027)) + '|\n'
    report += '''
原贪心确认成熟意图178→172，复合代理+29.07%→+39.81%；原14为193→185、+15.67%→+30.95%，这些全期有利结果保留。原14的2022从−17.14%减至−3.11%，2023从−2.78%转为+3.36%；2021、2024也正，均为局部支持。但2022仍负，2026从−7.66%降至−8.75%，2024也由+14.31%降至+8.30%。确认族原贪心2022−6.66%、2023−2.69%，两年比旧matched更差。

原14onlinePG全部六时钟2022均负；确认phase_1的2022+5.31%是有利反例，但2023−2.06%。两族各六时钟均没有同时2022/2023正复合代理，不更换入场相位救援。意图185/172不等于真实闭合交易次数，未核验盈利年份频率硬门。

## 盈利集中性及收口

以下仅是原时钟价格代理的事后归因，不是新策略或新增经济门。

|族|最大约10%正盈利机会占全部正盈利|去掉该组后的全期复合代理|
|---|---:|---:|
'''
    for family in FAMILIES:
        panel = result['schedules'][family + '_online_pg']['greedy']['panels']['all']
        report += f"|{family}|{pct(panel['top_positive_contribution'])}|{pct(panel['compound_without_top10pct_positive'])}|\n"
    report += '''
研究判断综合的是：更频繁更新没有稳定胜过原年度模型、原14仍不能使2022盈利、六时钟没有两下跌年同正，且仍依赖大赚机会。停止本固定扩展dailyPG直接交易化，不扫遗忘窗口、正则、分类阈值、期限或相位。此结论不扩大为所有在线估计无用；保留原14减亏、2023转正、全期复合和胜过弱training_mean对照的事实。

本轮没有新完整账户、标准32或独立双费用证据，新版中心四门、Q10/Q90、32点逐项/联合达标率及最新五项自检均不可得，不填0或写通过。价格代理失败不能当作已经运行的账户失败；只是现有固定表达尚缺升级账户的充分经济依据。

下一步应转向有区别的因果风险/机会信息，并先核对是否超越已失败的同期量压、价格顺序及状态表达；不能用更新更频繁或更换窗口代替信息增量。新版盈利年份频率允许不利环境少参与，但仍要在实际策略上满足收益、回撤、亏损年严格正收益及32/32。

本轮正式FULL与报告副本核对表示证据完整；不表示总体稳健目标已达成。额度仍余8轮，暂不暂停十轮研究，也不启动未经授权的EX099。
'''
    review = {'status': 'ROOT_SCIENTIFIC_REVIEWED', 'judgment': judgment,
              'new_models': result['new_daily_models'], 'new_accounts': 0,
              'native_followup_supported': False, 'objective_achieved': False,
              'positive_evidence': 'original14 selectedmean+0.0700pp; greedy2022 reducedloss,2023positive; both selectedmeans above weaktrainingmean',
              'counterevidence': 'original14 all6clocks2022negative; no6clock bothdownpositive;2026worse; no stable MSE advantage vs annual',
              'next_direction': 'distinct causal information beyond failed contemporaneous volume/sequence/state; no dailyPG window rescue'}
    g.write(OUT / 'root_review.json', review)
    reference = g.close_component(90, component_id='MATURE-EXPANDING-DAILY-PROBABILITY-GAIN', entrypoint='forecasts',
        judgment=judgment, status=g.m.ComponentTestStatus.INEFFECTIVE, report=report,
        results={name: OUT / name for name in ('statistics.json', 'verification.json', 'forecasts.csv', 'input_checks.json', 'root_review.json')} |
                {'closeout_driver.py': Path(__file__)})
    with (path / 'src/online_pg/closeout.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print({'experiment': exp.experiment_id, 'COMPONENTS': reference.revision, 'FULL': 'PASS',
           'report_copy': 'EXACT', 'completed': 2, 'remaining': 8, 'new_accounts': 0})


if __name__ == '__main__':
    main()
