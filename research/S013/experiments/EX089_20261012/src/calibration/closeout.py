"""EX089 scientific negative result, full public component delivery and report copy."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402

OUT=ROOT/'.tmp/s013-new-goal/result089'


def pct(value):
    return '不可得' if value is None else f'{100*value:.4f}%'


def main():
    exp,path,plan,refs=g.stage(89)
    result=g.read(OUT/'statistics.json')
    audit=g.read(OUT/'verification.json')
    assert audit['status']=='PASS' and audit['bootstrap_records_checked']==6000 and audit['state_windows']==3270
    assert all(result['bootstrap']['summary'][family+'_mse_improvement_vs_matched']['ci95'][1]<0 for family in ('confirmation','original14'))
    judgment='固定20成熟issued残差校准没有稳定净增量：两族配对误差恶化约19%，选中均值均负，原时钟2023/2026更差；保留2022局部减亏及2024改善，不进入原生账户，不扫描窗口救援。'
    report=f'''# EX089：知道过去预测错了，能否让当前买入更可靠

{judgment}

通俗说，策略发现最近已经结束的机会赚得比当时预计少，就调低当前预计收益。这确实减轻了部分2022代理损失，但也容易追着已经发生的涨跌跑，2023和2026没有变好。第一轮研究完成，总体稳健达标目标尚未达成。

## 新目标与授权边界

用户批准的新版四门：整体净年化至少同口径正buyhold的1.5倍、每自然年回撤严格更小、全部buyhold盈利年份合并每60日至少4实际闭合交易、每个buyhold亏损年份实际净收益严格为正；中心及标准32点都要通过。全期频率仅诊断，年度最终涨跌只用于事后验收，不能输入策略。

MANDATE/7及用户原文、冻结gates_v2.py已发布。公共SE全期频率指标不表达正年份合并条件，研究校验器单独按真实退出日期计算，不冒充公共全期字段，不修改平台或旧候选资格。门的边界合成6类及5类拒绝PASS，首次合成中0.15与1.5*0.1浮点相等假设修正为精确乘法边界，没有真实数据或经济规则更改。

仅原510500.SH开发池、HFQ固定锚、不额外叠加现金分红、100万元/整手100、单侧10bp、1%固定执行合同。最多EX089–EX098十轮，结束暂停，不授权EX099。当前1/10完成、剩余9，真实新增账户0。

## 为什么与旧近期状态不同，以及竞争解释

EX0842022历史盈利结构偏乐观，EX086/87盈利幅度局部有信息但2022净选择仍负，提示估计时钟可能滞后。EX085只取最近20成熟标签的raw胜率/均值作新特征，未使用当时已经发行的预测误差；本轮直接校准同一issued预测，并保留raw均值控制。

校准具有严格恒等式：当前q+过去20(actual−当时q)平均 = raw20均值+(当前q−过去20q均值)。它没有新增独立市场信息，可能只是旧状态的再表达；成熟至少等待四日，不能知道今天机会未来会亏。原14/确认已经被反复研究，不能将本轮当独立封存验证。

## 事前固定方法和独立核验

只复用EX087两族110概率+赚幅净预测。当前T取以前发行q有限、真实h4标签有限且label_end<=T的最近20条，同日已经成熟可用，不年重置、不回填；无20完整支持或当前q缺失为NA。

每族4表达：historical原q、matched同20支持原q、rawmean相同20实际标签均值、calibrated误差修正q。窗口20沿用EX085以匹配，不扫窗口/方向/阈值。使用原1635T轴和原h4扣费OPEN标签，未来尾部truth缺失仍保留当时决策；不使用未来年份标签选规则。

合成10类检查/11类拒绝PASS；独立400条联测48钟/6000数量PASS；真实3270成熟窗口及trace、全部48时钟、12×500块抽样独立标量复算PASS。原historical所有时钟与EX087逐字段精确一致；实际分析1次，0新fit/provider/账户。

## 十二项固定诊断

500次原T轴重叠40日块seed13，固定实际预测与全窗入场选择，不在拼接块重模拟时钟，不重拟合；至少20样本/400有效、LINEAR95%描述区间。误差改善正表示更准，均值差为百分点，不是账户年化差或新硬门；同开发池研究选择及多重比较未校正。

|数量|点估计|95%描述区间|有效次数|
|---|---:|---:|---:|
'''
    for key,row in result['bootstrap']['summary'].items():
        interval=row['ci95']
        report+=f"|{key}|{pct(row['value'])}|"+(f"[{pct(interval[0])}, {pct(interval[1])}]" if interval else '不可得')+f"|{row['valid_replicates']}|\n"
    report+='''
相对matched原预测，确认/14误差分别恶化约19.19%/19.23%，区间整段为恶化；相对raw均值没有稳定优势。校准选择的成熟净均值确认−0.1074%、14−0.0067%，两者区间含零。不能把知道历史错误视为已经知道下一次错误。

## 全部重叠机会与年度

价格代理允许机会重叠，以下每格为成熟正选择数/平均净标签，不等于实际闭合交易或年度净账户收益。

|表达|全池|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for name in result['panels']['all']:
        rows=[result['panels']['all'][name]]+[result['panels']['year_'+str(y)][name] for y in range(2020,2027)]
        report+='|'+name+'|'+'|'.join(f"{r['mature_positive']}/{pct(r['positive_mean'])}" for r in rows)+'|\n'
    report+='''
## 全部48个入场时钟

精确复用EX083原贪心及全轴i%5五相位，固定h4及退出优先/同T不重入规则。按入场年归组的价格复合不等于自然年连续账户收益；各钟数量和持有不同，不称等笔数对照或标准32点，不择有利年份/相位。

|表达/时钟|成熟数|全期复合|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for name,clocks in result['schedules'].items():
        for clock,row in clocks.items():
            p=row['panels']
            report+=f"|{name}/{clock}|{p['all']['mature']}|{pct(p['all']['compound_net_proxy'])}|"+'|'.join(pct(p['year_'+str(y)]['compound_net_proxy']) for y in range(2020,2027))+'|\n'
    report+='''
原贪心确认校准全期复合−13.66%，2022−1.66%、2023−6.91%、2026−25.39%；14校准全期+4.08%，2022−7.74%、2023−6.60%、2026−21.24%。2022对旧matched减亏、2024分别+20.35%/+28.53%是保留的有利证据；它们没有形成跨年份可靠改善。

## 收口及下一步依据

综合净选择为负、相对旧预测误差明显变差及原时钟下跌年仍亏，停止本固定20误差均值校准，不用更换窗口/threshold/相位救援。该判断不一般化为所有误差监控、在线估计或风险识别无用，也不由CI自动增加经济否决门。

没有新账户及标准32/独立双费，新版四门实际策略状态、Q10/Q90及32点逐项/联合达标率本轮不可得，不填0或通过。下一条不同的机制假说是保持同一P+G职责，直接用真正成熟的新标签更新估计，区分年度冻结与时间顺序更新；校准失败已经反驳简单加最近误差，不能再改窗口重复。

正式FULL与副本核对完成只表示该轮证据完整，不表示总体目标达成。
'''
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'new_models':0,'new_accounts':0,
            'native_followup_supported':False,'objective_achieved':False,'next_direction':'maturity-driven expanding estimator vs frozen annual P+G, no20window rescue'}
    g.write(OUT/'root_review.json',review)
    ref=g.close_component(89,component_id='ISSUED-H4-MATURE-RESIDUAL-CALIBRATION',entrypoint='decisions',
          judgment=judgment,status=g.m.ComponentTestStatus.INEFFECTIVE,report=report,
          results={name:OUT/name for name in ('statistics.json','verification.json','states.csv','forecasts.csv','input_checks.json','root_review.json')}|{'closeout_driver.py':Path(__file__)})
    with (path/'src/calibration/closeout.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print({'experiment':exp.experiment_id,'COMPONENTS':ref.revision,'FULL':'PASS','report_copy':'EXACT','completed':1,'remaining':9})


if __name__=='__main__':
    main()
