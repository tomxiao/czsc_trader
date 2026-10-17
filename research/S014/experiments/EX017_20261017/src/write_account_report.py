"""Human-readable interpretation of the fixed, audited stage-three comparisons."""
from pathlib import Path
import json
import pandas as pd
EX=Path(__file__).resolve().parents[1]
NAMES={'parent_H1':'父条件持有1天','parent_H3':'父条件持有3天','high_H3':'仅高环境持有3天','high_H3_low_H1':'高环境3天／低环境1天'}
def main():
    result=json.loads((EX/'others/comparison.json').read_text(encoding='utf-8'))
    audit=json.loads((EX/'others/account_audit.json').read_text(encoding='utf-8'));assert audit['status']=='PASS'
    assert result['all_targets_pass_count']==0
    conclusion='四方案连续账户对照已完成，全部满足全期频率，0个满足所有年度收益与回撤目标。高环境筛选存在全期改善，但年度不稳；低环境缩短至1天未稳定改善高环境单独交易。建议保留阶段三，先定位上涨覆盖缺口与持仓亏损，不进入阶段四。'
    result['conclusion']=conclusion
    (EX/'others/comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# S014 阶段三：四方案连续账户对照','',conclusion,'',
        '## 固定约定与实际执行','',
        '评价期2020-01-01至2026-10-15，实际1642个交易日为2020-01-02至2026-10-15。每账户初始10万元，连续计账，不按年重置，不在截止日强平。只做多、全可用现金、100股整手；每侧成交金额0.1%费用；后复权研究价格；前一日收盘上浮1%限价买入，允许更优开盘价成交，日内触价即按计划数量成交；卖出按原开盘价／跌停开盘后反弹1价位规则。四方案及BuyHold均使用原SRT/TXE合同。', '',
        '父条件是低开后收阳线；高环境是阶段二原年度因果校准的相对环境分层，不是未来收益标签。持有期限在入场信号日确定，从实际成交日计数；H1为买入下一交易日退出，H3为买入后第3个交易日退出。环境首个可用日为2020-10-13，之前保持现金，但完整2020年度仍验收。限价买单仅尝试一次，未成交后清空旧入场周期；四方案同规则。', '',
        'BuyHold于2020-01-02实际买入后一直持有。其全期净收益186.48%，末资金286,476.58元。研究全部使用已见开发池，不是独立验证。', '',
        '## 四方案结果','',
        '| 方案 | 末资金（元） | 全期净收益 | 全期最大回撤 | 年收益达标 | 年回撤达标 | 闭合交易 | 每60日平均交易 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in result['summaries']:
        lines.append(f"| {NAMES[row['variant']]} | {row['ending_equity']:,.2f} | {row['total_return']:.2%} | {row['full_max_drawdown']:.2%} | {row['annual_return_pass_count']}/7 | {row['annual_drawdown_pass_count']}/7 | {row['closed_trades']} | {row['frequency_per_60']:.2f} |")
    lines += ['', '全期最大回撤为诊断，不替代逐年回撤硬门。频率按60×闭合交易数÷1642计算，门槛为3，四方案全部满足；H1最终无持仓，其他三方案各保留1笔未平仓交易，未计入闭合笔数。', '',
        '## 逐自然年收益','',
        '| 年份 | BuyHold | 收益门槛 | 父H1 | 父H3 | 高H3 | 高3／低1 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    annual=pd.DataFrame(result['annual']);variants=list(NAMES)
    for year,g in annual.groupby('year'):
        r=g.iloc[0];threshold=f"≥{r.required_return:.2%}" if r.buyhold_return>0 else '>0%'
        vals=[f"{g.loc[g.variant.eq(v),'return'].iloc[0]:.2%}"+(' ✓' if g.loc[g.variant.eq(v),'return_pass'].iloc[0] else '') for v in variants]
        lines.append(f"| {year}{'（截至10月15日）' if year==2026 else ''} | {r.buyhold_return:.2%} | {threshold} | "+' | '.join(vals)+' |')
    lines += ['', '✓表示当年收益达到原目标。2026部分年度使用实际收益，不年化。年度收益由上一年末净值衔接；第一年以10万元为起点。', '',
        '## 逐自然年最大回撤幅度','',
        '| 年份 | BuyHold | 父H1 | 父H3 | 高H3 | 高3／低1 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for year,g in annual.groupby('year'):
        vals=[f"{g.loc[g.variant.eq(v),'max_drawdown'].iloc[0]:.2%}"+(' ×' if not g.loc[g.variant.eq(v),'drawdown_pass'].iloc[0] else '') for v in variants]
        lines.append(f"| {year} | {g.buyhold_drawdown.iloc[0]:.2%} | "+' | '.join(vals)+' |')
    lines += ['', '×表示未严格小于BuyHold。每年从包含上一年末净值的曲线重新计算年度高点；不能跨年沿用峰值，也不能漏掉年初第一个交易日的下跌。', '',
        '## 哪些机制兑现，哪些没有','',
        '1. 高环境筛选有全期改善：父H3净收益48.66%，仅高H3为87.38%，增加38.73个百分点，闭合交易由201降至146。但2021收益由−7.01%变为−14.91%，2025由−9.69%变为−13.50%；不能说筛选每年有效，更不能称高环境安全。高H3的2021年度回撤40.45%，超过BuyHold的37.75%。',
        '2. 单纯延长持有并不普遍更好：父H1全期58.75%，父H3为48.66%。H3在2020、2023、2024更强，H1在2021和2026更强。2026父H1虽赚78.48%，仍不足原年度门槛196.46%。',
        '3. 低环境改为短持有有取舍：混合方案83.68%，高于父H3，但低于仅高H3的87.38%；混合的闭合交易增加79笔、累计费用增加19,883.69元，全期回撤也更深。不过混合方案年度回撤7年全部达标，而仅高H3为6年，不能用单一全期收益代替全部年度目标。',
        '4. 主要短板是年度盈利，不是交易太少。2021、2022、2025、2026四方案收益全部未达标。高H3在2022下跌年份仍亏17.58%，2025基准上涨26.79%时却亏13.50%，说明既有亏损交易，也有上涨覆盖缺口。', '',
        '## 基于原账本的诊断与下一步','',
        '高H3在2021、2025、2026分别有127、114、93个完全空仓日（当天开盘前和收盘后均无仓位）。仅把BuyHold这些日期的日收益连乘，分别为+58.29%、+43.28%、+60.71%。这是对已发生日期的收益分解，不是事前可交易策略，也不能直接当作可补回的收益；它证明上涨并不只发生在目前的修复持仓内。2022完全空仓日对应基准−19.35%，但实际账户全年仍亏，表明增加持仓时间本身不是答案。', '',
        '建议暂留阶段三，不进入阶段四。先固定高H3和混合作为对照，用现有日期和交易记录分开检查：上涨缺口究竟来自高环境筛选、低开收阳入场条件，还是3日退出后未重新入场；同时定位2022、2025的实际亏损交易。根据可区分的原因设计最小构造对照，不直接扩大参数搜索、也不先购买公告或增加数据。若事前条件仍无法区分好坏机会，再有依据地回到阶段二补信息。', '',
        '本次授权的四方案对照目标已达成；策略经济目标尚未达成。后续方案研究、阶段四、冻结均未据此自动启动。', '',
        '## 数据与验证证据','',
        '- 预窗口授权上限15次，实际Tushare调用8次（失败也计数规则保持），剩余7次未使用。补齐2019-12日历、交易状态及2019-12-31的后复权／不复权行情。补数期间一次本地序列化错误已保留，修复后从缓存继续，未重置计数。',
        '- 通过公开ProviderBinding和批次上下文组合已认证数据资产；原2020—2026数据逐值、类型与哈希保持。5类完整数据、15项子区间及无provider的worker读取通过；合成质量证据由固定原始行情重新计算，复合因子摘要不冒充供应商原始因子序列摘要。',
        '- 四账户通过公开evaluation.prepare/evaluate_many，2个进程、各1原生线程、种子17，全程禁止网络。完整信号、订单、成交、现金、权益、交易与BuyHold均保存在正式EvaluationEvidence中。',
        '- 前缀／未来扰动37项检查通过；独立账本审计逐日核对4×1642日真实持仓与影子持仓、买卖成交、无订单日，以及整数手、限价、费用、现金和权益。含4项跨复权尺度合成边界检查，共54,616项断言通过。四份完整BuyHold证据一致，首笔2020-01-02。',
        '- 保留技术失败：v1日历输入声明缺失，在准备阶段终止；v2四次请求因布尔观察值不符合SRT数值展示契约失败；v3仅修正声明／展示类型，经济函数AST相同，完成4个正式账户。没有利用失败改动参数或筛选结果。成功候选为C0009—C0012，前序身份保留来源，不充当完成账户。',
        '- 历史数据真实发布时间／修订史未核验，沿用原已披露边界。研究状态机通过本窗口逐日核对，不据此宣称可直接接入任意PTE实际账户。', '',
        '数据来源、绑定及完整账户引用见实验 `others/account_results.json`、`others/prewindow_inputs.json`、`others/binding_*.json`；年度表见 `others/annual_comparison.csv`，占用诊断见 `others/occupancy_diagnosis.csv`。交付关联正式证据引用；本地assets须与Git材料共同保留。FULL/PASS仅表示交付完整性，不表示年度目标达标。', '']
    (EX/'protocols/account_report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('REPORT_READY',len(lines))

if __name__=='__main__':main()
