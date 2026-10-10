"""Reproduce complete exit-anchor category evidence and cash-year accounting."""
from collections import Counter
from common import ROOT, SRC, PROTOCOLS, read, write, RUNS

CENTERS = ('center', 'MEAN', 'BODY', 'TIME_CLOSE', 'TIME_BODY')
CATEGORIES = ('BELOW', 'EQUAL', 'ABOVE', 'NONE')


def main():
    data = read(ROOT / '.tmp/ex042-diagnosis/anchors_v2.json')
    assert data['status'] == 'PASS' and data['new_account_evaluations'] == 0
    assert len(data['accounts']) == 37 and data['summary']['native_signal_rows'] == 60532
    text = '''# S013：下跌定时退出的信号价格状态与真实资金路径

RSCH阶段三。用户已授权自主完成研究，无需逐轮评审。原S013数据固定2020-01-02至2026-09-30，四项经济目标与13维完整数值域保持。本轮零新增完整账户，精确复用原C2132中心及32个参数邻点、MEAN/BODY旧背景和EX041两个新方向门的既有账户，共37个不同原生账户、60,532行信号及实际执行日。原33账户共享同一市场路径，不能视为33个独立样本；四个额外中心分别报告。

## 为什么先诊断

EX041把严格价格确认缩小到下跌TIME退出后的再次买入，两配置116笔足够，却均使2023亏损约1.25%。不能把信号入场价以下的退出直接视为应阻止再次买回的理由。EX016已经研究过信号相对入场价：排除退出当日raw路由变化并去重的2023负组30事件随后3日均上涨0.3690%，正组36事件下跌0.1261%，10日方向又改变。这些重叠事件的未来窗口统计是反证，不能挑窗或替代新策略现金路径。本轮不计算新的未来观察窗。

S013源码/协议重复核查没有发现完全相同的“仅低于锚点的bear TIME退出后对再次买入加方向门”结构；EX041未分退出价类别，EX016按价格状态改变是否TIME退出。结构不同并不证明有效，完整新账户仍是必要证据。

## 事前固定的描述方法

入场锚点是该账户本次信号入场T的HFQ Close。每次持仓信号退出记录退出前active_route与最终原因；仅bear TIME退出按当时Close严格低于/等于/高于锚点分为BELOW/EQUAL/ABOVE。其他退出和初始状态为NONE。没有新增幅度、容差、年份例外或数值门槛。空仓拒绝、资格失败、raw路由变化保留退出上下文；任意路线成功信号入场清除当前上下文，并为持仓保存其入场来源上下文。

全部退出、后续bear资格机会、任意路线再次入场、方向拒绝、未再次入场和末尾持仓保留。机会年份按信号T，实际资金年份按T+1执行日期，2019末信号与2020首执行分别保留。退出当日raw路由已变的bear TIME也保留。全部日期、类别、自然年和空组完整展示。

37账户的原生序列化证据、候选/实现/依赖/绑定/参数/lineage身份、全部信号特征与状态、公共日历1636对T→T+1、实际现金/数量/价格/费用及五基准账本核对。资金有两套完整分组：按当日信号前退出上下文；按实际cycle首次BUY的decision_id对应的信号持仓来源。每笔fill保存自身来源及不一致计数，逐日按真实库存、成交价格、费用重建净权益变化，两套分组均对回全年和全窗原账户。OPEN尾仓和跨年cycle完整保留，跨年整笔PnL不是年度收益。

## 中心账户的全部类别

BELOW/ABOVE简称信号价格低于/高于入场锚点，与实际净亏损/净盈利不同。以下为既有路径计数，不能当作新增门的收益。

|账户|类别|bear TIME退出|随后bear资格机会|该类别bear信号入场|机会Close>前收|机会Close>Open|方向拒绝|
|---|---|---:|---:|---:|---:|---:|---:|
'''
    for label in CENTERS:
        account = data['accounts'][label]
        for category in CATEGORIES:
            stat = next(row for row in account['statistics'] if row['year'] == 'ALL' and row['category'] == category)
            days = [row for row in account['all_native_days'] if row['pre_context'] == category]
            opportunities = [row for row in days if row['opportunity'] and row['raw_route'] == 'bear']
            entries = sum(row['entry'] and row['raw_route'] == 'bear' for row in days)
            text += f"|{label}|{category}|{stat['bear_time_exits']}|{len(opportunities)}|{entries}|{sum(row['close_up'] for row in opportunities)}|{sum(row['body_up'] for row in opportunities)}|{stat['direction_rejections']}|\n"
    text += '\n## 全部自然年的真实资金分解\n\n'
    text += '以下按实际持仓入场来源分组，各类别净权益变化除以该年真实期初权益；四组贡献之和严格等于当年账户收益。这是已有政策的会计分解，删除某组交易不会得到表中其他组组成的新收益。NONE包含其他信号来源。\n\n'
    text += '|账户|执行年|实际年度收益|BELOW贡献|EQUAL贡献|ABOVE贡献|NONE贡献|\n|---|---:|---:|---:|---:|---:|---:|\n'
    for label in CENTERS:
        for annual in data['accounts'][label]['annual_cash']:
            if annual['year'] == 'ALL':
                continue
            parts = {row['category']: row['holding_source_net_equity_change'] / annual['opening_equity'] for row in annual['groups']}
            assert abs(sum(parts.values()) - annual['account_return']) < 1e-12
            text += f"|{label}|{annual['year']}|{annual['account_return']:+.4%}|" + '|'.join(f'{parts[key]:+.4%}' for key in CATEGORIES) + '|\n'
    original = [account for account in data['accounts'].values() if account['population'] == 'original33_dependent']
    assert len(original) == 33
    counts = Counter()
    for account in original:
        counts.update(account['summary']['bear_time_categories'])
    text += '\n## 原33账户的覆盖与局限\n\n'
    text += f"原33路径的bear TIME类别合计为{dict(counts)}；这是同市场参数扰动路径的计数，不是独立事件样本或统计显著性。全部37账户的60,532行、每账户全年度两套资金分解及全部实际周期均在native-anchors正式证据中保留。\n"
    disagreements = {label: account['summary']['actual_buy_fill_source_disagreements'] for label, account in data['accounts'].items()}
    text += f"\n实际BUY fill来源与cycle首次来源不一致合计{sum(disagreements.values())}，逐账户与逐fill明示，没有静默重写来源。\n"
    decision = read(PROTOCOLS / 'decision.json')
    text += '\n## 研究判断与下一步\n\n' + '\n\n'.join(decision['conclusions']) + '\n\n' + decision['next_action'] + '\n'
    text += '\n## 技术修正与验证边界\n\n原诊断在account.date的微秒与valid_session集合的秒精度比较失败，原冻结源码和失败完整保留。显式v2仅一行比较将两侧时间单位转为ns后仍严格比较全部日期值、顺序和数量；其余状态/锚点/类别/统计函数AST完全相同。9种秒/微秒/纳秒组合通过，改日与缺日拒绝，原10项非法状态/价格/资金检查保留。完整37既有账户核对使用v2，零新增或重跑完整账户。\n\n诊断不新增经济硬门，不证明新规则收益或独立验证。FULL仅证据完整性。总参数敏感性改善目标仍未达成；未推进正式阶段四、冻结、PTE或生产。\n'
    target = SRC.parent / 'others/report.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    write(RUNS / 'conclusion.json', {'status': 'COMPLETE', 'objective_achieved': False,
        'unique_native_accounts_reused': 37, 'native_signal_rows': 60532,
        'new_account_evaluations': 0, 'new_business_configurations': 0,
        'cash_replays': 0, 'economic_targets': 'UNCHANGED', 'all_categories_all_years': True})
    print({'report': 'COMPLETE', 'unique_reused': 37, 'new_accounts': 0}, flush=True)


if __name__ == '__main__':
    main()
