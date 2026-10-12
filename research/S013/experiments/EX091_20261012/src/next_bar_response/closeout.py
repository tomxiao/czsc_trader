"""EX091 scientific review and exact report-copy delivery."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402
OUT=ROOT/'.tmp/s013-new-goal/result091'


def pct(value):
    return '不可得' if value is None else f'{100*value:.4f}%'


def main():
    exp,path,plan,refs=g.stage(91)
    result,audit=(g.read(OUT/name) for name in ('statistics.json','verification.json'))
    assert audit['status']=='PASS'
    assert result['new_models']==12 and result['new_accounts']==0
    assert all(row['panels']['year_2022']['compound_net_proxy']<0 for row in result['schedules']['augmented'].values())
    judgment='下一bar量响应有微弱同向描述，但控制后无稳定净增量；配对预测未改善，原贪心全期复合代理下降，2022/2023仍负。停止本固定交互，不翻方向或扫描参数。'
    report=f'''# EX091：下跌成交之后的价格反应，能否帮助下一次买入

{judgment}

通俗说，有人卖出后价格很快回升，并不表示下一天买入仍然划算。这个反应有少量同向现象，但加入旧信息对照后优势很小；在真实时间顺序选择机会时，也没有解决下跌年份亏损。第三轮完成，总体稳健达标目标尚未达成。

## 研究问题与最强反证

EX075只检验同一bar成交量与负实体幅度，EX068检验下跌顺序，EX061检验尾段恢复。这里首次直接检验同一来源下跌成交量与紧接下一bar的实体反应。新交互不等于新增独立市场数据；量不能识别主动买卖，反应已经发生在T日，未必能预测T+1入场之后。日内最多七对相互依赖，不能当作独立样本。

固定表达：来源为同日第1至7个严格负实体，b=log(C/O)；S为按来源成交量加权的下一bar实体均值，U为同来源未加权均值，X=S−U。第8bar不作来源、不跨日，假设较大X对应较高原h4扣费收益；不按结果翻号。

对照保留原14、EX061两项端点、EX068四项下跌顺序及幅度、同期负实体均值/量协方差/过去20量时钟、U/来源数/来源平均负幅、过去20量时钟投射下一响应，共27控制。过去20只用T以前完整日，不含T。无来源或来源量为零使X缺失，真实零反应保留为0；不跳过缺量日、不缩窗。

## 授权、目标与方法

新版四门为净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60交易日至少4笔真实闭合交易、每个buyhold亏损年真实连续账户收益严格为正；中心及标准32点均须联合通过。年度最终盈亏只用于事后验收，未输入本轮模型或挑选训练年份；全期频率只诊断。

仅S013原510500.SH开发池2020-01-02..2026-09-30及固定HFQ锚，排除额外现金分红，原100万元/100单位整手/单侧10bp/1%执行合同保持。h4标签为Open[T+5]/Open[T+1]*0.999/1.001−1，真实成熟T+5；没有使用High/Low、外部数据或新账户。

固定年度2021..26扩展训练：同28特征完整、2020起以前年度标签已成熟且label_end严格早于本年首个完整轴T，至少40样本。训练ECDF中点秩、ridge10和未罚截距；controls与controls+X同支持，历史均值为第三控制。当前预测只依赖特征，不取未来标签或全年未来数量，尾部无真值仍保留预测。没有2020预测、没有参数或阈值搜索。

原轴500次重叠40日块seed13、20样本/10残差自由度/400有效次数、LINEAR95%区间；是同开发池描述诊断，不是标准32或独立封存验证，也未校正反复研究与多重比较。固定预测与时钟选择不在抽样中重拟合或重模拟。

## 正反证与完整数量

|关系|点估计|95%描述区间|样本|
|---|---:|---:|---:|
'''
    for name in ('raw','partial'):
        row=result[name]
        ci=result[name+'_bootstrap']['ic95']
        report+=f"|{name}|{row['value'] if row['value'] is not None else '不可得'}|{ci if ci else '不可得'}|{row['n']}|\n"
    report+='''
原始相关约0.043、控制后约0.017；两个区间均含零。控制后部分年份为正，是应保留的有利事实；2020/2025与一个固定相位反向，也须保留。控制后弱描述不足以建立可交易净优势。

|固定数量|点估计|95%描述区间|有效次数|
|---|---:|---:|---:|
'''
    for key,row in result['bootstrap']['summary'].items():
        ci=row['ci95']
        report+=f"|{key}|{pct(row['value'])}|{('['+pct(ci[0])+', '+pct(ci[1])+']') if ci else '不可得'}|{row['valid_replicates']}|\n"
    report+='''
比同支持controls的误差改善为−0.0230%，比历史均值为−3.6669%，后者区间整段为恶化；正预测选择的成熟均值仅+0.0502%，相对controls增加+0.0022个百分点，区间含零。均值和误差改善不是账户年化。停止判断同时考虑原时间顺序经济结果，不把区间另加为用户硬门。

## 全部年度与固定相位

|范围|raw|partial|partial样本/秩/残差自由度|比controls误差改善|新正选择均值|比controls选择差|
|---|---:|---:|---:|---:|---:|---:|
'''
    for key,row in result['panels'].items():
        r=row['partial']
        q=row['quantities']
        report+=f"|{key}|{row['raw']['value']}|{r['value']}|{r['n']}/{r['design_rank']}/{r['residual_df']}|{pct(q['augmented_mse_improvement_vs_controls'])}|{pct(q['augmented_positive_mean'])}|{pct(q['augmented_positive_minus_controls'])}|\n"
    report+='''
## 训练可得性与独立核验

|测试年|成熟训练数|完整特征预测数|状态|
|---|---:|---:|---|
'''
    for row in result['fit_trace']:
        report+=f"|{row['year']}|{len(row['train_positions'])}|{len(row['test_positions'])}|{row['reason'] or 'AVAILABLE'}|\n"
    report+='''
纯特征10类合成/19类拒绝、独立特征50全部前缀、主统计8类/3拒绝、独立统计7类/9相关状态边界通过。首次主合成把尾部未知标签误填为有限，受到成熟契约拒绝；仅修正测试保持尾部缺失，真实科学规则未改。声明第一次选用证明字段不适配，发生在分配和真实读取前；改接有real_inputs=0的统计合成证明，未产生额外EX或账户。

原生缓存与已发布完整账户严格一致，原14/旧端点/顺序/同期量字段和HFQ净标签逐值或浮点容差一致；没有调用数据提供者。独立真实核验用逐bar标量复核全部特征/trace，独立ECDF与每个ridge正规方程/预测、全部相关及1000次相关块抽样、4×500预测数量、18固定时钟与年度面板；实际12模型一次研究，不因核验增加实验额度。

## 全部18时钟与集中性

复用原h4贪心以及全轴i%5五相位、退出优先同T不重入。价格复合按入场年归组，未计真实限价未成交/整手现金/尾部持仓估值；这些是机会代理，不是连续账户年度收益、最大回撤或实际闭合交易。

|表达/时钟|成熟数|全期复合|2020|2021|2022|2023|2024|2025|2026|最大约10%正机会贡献|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for name,clocks in result['schedules'].items():
        for clock,row in clocks.items():
            panel=row['panels']
            report+=f"|{name}/{clock}|{panel['all']['mature']}|{pct(panel['all']['compound_net_proxy'])}|"+'|'.join(pct(panel['year_'+str(y)]['compound_net_proxy']) for y in range(2020,2027))+f"|{pct(panel['all']['top_positive_contribution'])}|\n"
    report+='''
原贪心controls全期+18.71%，加入X为+6.86%；2022从−14.17%变为−16.30%，2023同为−9.37%。三个相位全期略改善是有利反例，全部六相位/贪心的2022仍负；不择相位、不翻方向救援。207成熟接受机会不等于真实闭合交易数，更不能替代盈利年份频率检查。

## 收口与下一步

该固定下一bar交互停止升级原生交易。结论限定于固定表达与本开发池，不宣称所有吸收/反应机制无效。下一条不同假说是控制各自边际之后，隔夜下跌和同日日内下跌的历史联合依赖是否识别较差的未来净机会；同时复核交易状态表达覆盖，避免不断给旧失败指标改名字。

当前3/10完成，剩余7轮，实际新增账户0。中心四门、标准32逐项/联合达标率、绝对收益Q10/回撤Q90及最新五项完整账户自检本轮不可得，不写0或通过。正式FULL/副本核对仅代表该轮证据完整，总体稳健目标尚未达成。
'''
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'new_models':12,'new_accounts':0,
        'objective_achieved':False,'native_followup_supported':False,
        'next_direction':'fixed20 overnight/intraday joint-negative dependence with marginals; review executable state design'}
    g.write(OUT/'root_review.json',review)
    ref=g.close_component(91,component_id='NEGATIVE-SOURCE-NEXT-BODY-VOLUME-RESPONSE',entrypoint='forecasts',
        judgment=judgment,status=g.m.ComponentTestStatus.INEFFECTIVE,report=report,
        results={name:OUT/name for name in ('statistics.json','verification.json','features.csv','forecasts.csv','availability.json','input_checks.json','root_review.json')}|{'closeout_driver.py':Path(__file__)})
    with (path/'src/next_bar_response/closeout.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print({'experiment':exp.experiment_id,'COMPONENTS':ref.revision,'FULL':'PASS','report_copy':'EXACT','completed':3,'remaining':7})


if __name__=='__main__':
    main()
