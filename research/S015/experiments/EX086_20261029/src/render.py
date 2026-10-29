"""Render the complete fixed census and bounded post-result interpretation."""
from study import WORK,HORIZONS,NAMES,read,save,digest

LABELS={'permission':'全部入场许可','entry_signal':'原策略入场脉冲'}


def pct(value):
    return '无样本' if value is None else f'{100*value:.4f}%'


def interval(value):
    x=value['interval_95']
    return '无有效抽样' if x is None else f'[{100*x[0]:.4f}, {100*x[1]:.4f}]'


def main():
    a=read(WORK/'others/analysis.json')
    validation=read(WORK/'others/result_validation.json')
    judgment={'analysis_sha256':digest(WORK/'others/analysis.json'),'work_complete':True,
        'conclusion':'S015-v1在原已研究样本内具有清楚的近端入场优势：全部入场许可在1交易日主期限的扣费均值、匹配增量均正，减少重叠后未消失；冻结入场脉冲结果同向。它不同于LITE原PAT缺乏清楚入场增量的诊断表现，但不是跨市场收益排名，也不是新增独立验证。',
        'strongest_counterevidence':'仅430个合格日频机会、64次许可、63个主期限完整标签，减少重叠后48个；只有2025与2026两个年份且原窗口反复参与策略开发。20日辅助期限中，许可去重后匹配增量转负，原入场脉冲原始与去重均负，因此近端优势不等于更长持有期持续占优。',
        'interpretation':'在这一历史样本和原研究执行合同下，入场许可本身筛出了更好的短期机会，结果并非只有套上原持有/退出状态后才出现。它支持继续区分入场信息与退出用途的研究方法；不能从两个信号集合的差异因果判定旧退出贡献，也不能把近端标签优势直接年化成策略收益。',
        'next_step':'建议保留S015-v1作为已有入场优势的研究参照，当前不调整冻结策略或退出参数。对S017继续先补证超跌修复的入场质量；若进一步研究S015，应单独约定未见样本或明确原退出如何利用近端机会的问题。本轮不自动开启后续实验或改变前瞻/生产安排。',
        'limits':['原已选择开发窗口，非未见验证；本轮统计不能消除历史参数及规则选择偏差。',
            'S015为A股ETF日频，样本2025—2026；S017为LITE30m，样本2019—2025，价格/成交合同也不同，不能直接比较收益数字高低。',
            '原HFQ_RESEARCH/RESEARCH_UNIT价格标签，不是未复权现金分红账本，不重复叠加分红。',
            '一次次日尝试的固定期限标签与冻结策略资金周期、重试、原退出不同，不是连续账户。',
            '20交易日块边际95%区间未做选择/多重比较校正；减少重叠不等于统计独立。',
            '仅复核原434行信号及109订单/108成交交集；结果核验独立检查汇总算术和保留抽样分位数，非第二次完整账户回放。'],
        'new_accounts':0,'new_parameters':0,'S017_budget_consumed':0,'freeze_changed':False}
    save(WORK/'others/judgment.json',judgment)
    lines=['# EX086：S015-v1冻结入场条件普查','',judgment['conclusion'],'',
        '用户要求复用入场普查方法，并明确沿用当前分支。本轮已完成1次S015单独诊断，S017剩余8轮额度未使用。'
        '原S015冻结身份、参数、资格、PTE和生产保持，不登记新候选、不新增连续账户。','',
        '## 对象、信号和执行','',
        '标的159326.SZ，当前S015-v1发布身份`'+a['release']+'`。沿用原434交易日窗口2025-01-02至2026-10-21、原日线及30分钟预热。'
        f"共{a['eligible']}个feature_ready且次日仍在窗口的合格日频时点。原434行信号包含预热种子与未就绪行，因此不能将434直接作为有效机会数。",'',
        '全部入场许可（permission）表示中心较3日前上移、收盘低于当日30分钟对数收盘中位数形成的中心，且修复空间达到原0.1729898661%门槛。'
        '它不受旧持仓状态筛选。原策略入场脉冲（entry_signal）还受active、旧退出及同日不反手影响，作为冻结策略参考。两者均由原公共SRT计算，没有重写冻结规则。','',
        '主观察期限事前固定为1个交易日，辅看3/5/10/20日。T收盘后信号，T+1尝试买入，持有N个交易日后T+N+1卖出。'
        '单边0.1%、买限价溢价1%、原0.001取整/涨停保护、日线范围触价及市价卖出均沿用原合同。'
        '原策略首日未成交后可能重试；这里每个时点仅次日尝试一次，不能称为复刻原账户。','',
        '价格采用原HFQ_RESEARCH/RESEARCH_UNIT及2024-12-31锚点。净价格标签=卖价×0.999/(买价×1.001)−1。'
        '这不是未复权真实现金分红账本，不额外叠加分红。单事件100研究单位，无资金再投资、账户机会互斥或连续仓位核算。','',
        '[事前协议](protocols/design.md) · [完整分析](others/analysis.json) · [输入身份](others/input_identity.json)','',
        '## 主期限：一天后的机会质量','',
        '匹配一般机会取相同合格总体，按计划入场年月×09:30匹配；所有入场为日频，实际相当于同月对照。'
        '对照包含目标自身，按目标事件数加权，故两信号集合的匹配均值不必相同。这是历史描述，不是提前使用当月未来收益交易。','',
        '|信号/样本|完整标签|平均净价格收益|匹配一般机会|增量（百分点）|胜率|平均盈利/平均亏损|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name in NAMES:
        v=a['horizons']['1']['signals'][name]
        for mode,label in [('raw','原始'),('nonoverlap','减少重叠')]:
            q,m=v[mode]['price'],v['matched_'+mode]
            lines.append(f"|{LABELS[name]}/{label}|{q['count']}|{pct(q['mean'])}|{pct(m['control_mean'])}|{100*m['difference']['mean']:.4f}|{pct(q['win_rate'])}|{q['payoff_ratio']:.3f}|")
    lines+=['',f"无筛选全部机会的1日完整标签为{a['horizons']['1']['all']['price']['count']}个，平均净价格收益{pct(a['horizons']['1']['all']['price']['mean'])}。"
        '全部许可出现64次、原入场脉冲55次，各有1次次日未成交。完整标签63/54，与原账户实际买单的关系另以订单复现核对，不强制逐一映射。','',
        '减少重叠按信号时间先后保留，下个信号必须严格晚于前一个的固定持有与退出区间；不看结果挑样本。'
        '许可减少重叠后仍有48个完整标签，平均净收益反而稍高，当前优势没有因减少重复覆盖而消失。'
        '不能据此推断去重规则必然提高连续账户收益。','',
        '## 不确定性、年度和集中性','',
        '主期限20交易日连续块、1000次、种子17；各集合共享抽样索引，每次重估匹配控制均值。以下为边际描述性95%区间，'
        '不含全部选择偏差或未来状态变化，不是新增的统一显著性验收门。','',
        '|信号/样本|净均值区间（%）|匹配增量区间（百分点）|有效/空重抽样|',
        '|---|---:|---:|---:|']
    for name in NAMES:
        v=a['horizons']['1']['signals'][name]
        for mode,label in [('raw','原始'),('nonoverlap','减少重叠')]:
            b=v['bootstrap_'+mode]
            lines.append(f"|{LABELS[name]}/{label}|{interval(b['price_mean'])}|{interval(b['matched_difference'])}|{b['price_mean']['valid_replicates']}/{b['price_mean']['empty_replicates']}|")
    lines+=['','许可去重后的净均值和匹配增量区间均在正侧，支持这份开发样本中的近端优势。'
        '但只有48个标签、不到两年，不能当作跨多个独立市场周期的证明。','',
        '|信号|计划入场年|完整标签|净均值|匹配增量（百分点）|','|---|---:|---:|---:|---:|']
    for name in NAMES:
        for year,y in a['horizons']['1']['signals'][name]['years'].items():
            q=y['raw']['price']
            lines.append(f"|{LABELS[name]}|{year}|{q['count']}|{pct(q['mean'])}|{100*y['matched']['difference']['mean']:.4f}|")
    lines+=['','2025与2026的许可平均净收益均正，2026更强。年份只作诊断，不设置年份交易开关或事后年度门槛。','',
        '|信号|有完整标签月份|正均值月份|最大单笔正收益份额（原始/去重）|最大年度正收益份额（原始/去重）|',
        '|---|---:|---:|---:|---:|']
    for name in NAMES:
        v=a['horizons']['1']['signals'][name]
        months=[x['price'] for x in v['months'].values() if x['price']['count']]
        c,d=v['concentration_raw'],v['concentration_nonoverlap']
        lines.append(f"|{LABELS[name]}|{len(months)}|{sum(x['mean']>0 for x in months)}|{pct(c['largest_event_share'])}/{pct(d['largest_event_share'])}|{pct(c['largest_year_share'])}/{pct(d['largest_year_share'])}|")
    lines+=['','份额只对正事件收益的算术合计计算，不是净账户盈利贡献，也不保证亏损抵消后的稳定性。逐月数据及分母完整保存在analysis。'
        '主期限匹配控制每目标中位20个事件、最少13个，许可及脉冲均无仅自身或全为目标的格子。','',
        '## 所有固定期限：保留长持有的反证','',
        '|持有交易日N|信号|原始完整数|净均值|匹配差（百分点）|去重完整数|去重净均值|去重匹配差（百分点）|',
        '|---:|---|---:|---:|---:|---:|---:|---:|']
    for n in HORIZONS:
        for name in NAMES:
            v=a['horizons'][str(n)]['signals'][name]
            x,y=v['raw']['price'],v['nonoverlap']['price']
            lines.append(f"|{n}|{LABELS[name]}|{x['count']}|{pct(x['mean'])}|{100*v['matched_raw']['difference']['mean']:.4f}|{y['count']}|{pct(y['mean'])}|{100*v['matched_nonoverlap']['difference']['mean']:.4f}|")
    lines+=['','1/3/5/10日两集合在原始和减少重叠样本中均有正匹配差。到20日，许可去重匹配差约−0.129个百分点，'
        '原入场脉冲原始约−0.129、去重约−1.216个百分点；不能把近端优势理解为越久持有越好。'
        '长期限样本更少且存在截尾，不能按本表事后挑“最佳退出天数”。','',
        '## 信息标签、路径和不可评价事件','',
        '|N|信号|收盘信息均值|最低收盘偏离均值|最高收盘偏离均值|原始事件状态|',
        '|---:|---|---:|---:|---:|---|']
    for n in HORIZONS:
        for name in NAMES:
            v=a['horizons'][str(n)]['signals'][name]['raw']
            lines.append(f"|{n}|{LABELS[name]}|{pct(v['information'].get('mean'))}|{pct(v['close_path_min'].get('mean'))}|{pct(v['close_path_max'].get('mean'))}|{v['status']}|")
    lines+=['','信息标签为信号日完成收盘到T+N完成收盘，未计执行与费用。路径仅取持有期完成日Close并含0，'
        '不是柱内高低点、可赚利润或账户回撤。无入场、无退出、右截尾不补零、不顺延。主期限未成交事件仍保留信息标签，分母不同。','',
        '|N|全部机会状态|','|---:|---|']
    for n in HORIZONS:
        lines.append(f"|{n}|{a['horizons'][str(n)]['all']['status']}|")
    lines+=['','## 验证、解释和下一步','',
        f"10组合成检查与Ruff通过，独立结果核验覆盖{validation['event_rows']}条事件标签、10个信号×期限格。"
        '公共SRT复现原434行信号的数值，当前与历史采用相同CSV解析表示，日期精度及空字段表示统一，未扩大数值容差。'
        '公共冻结价格规则与TXE复现109个订单、108个成交的价格与时点。结果核验检查成本、成员、去重、均值、匹配及保留抽样分位数；'
        '未再次独立重算全部历史标签或完整账户，未执行全仓回归。','',
        judgment['interpretation'],'',judgment['strongest_counterevidence'],'',
        '与LITE比较时，研究问题和诊断框架相同，但市场、标的、频率、样本、复权与成交合同不同。'
        '可以说S015在自身样本内显示出LITE原PAT没有显示的近端入场增量；不能用0.95%和LITE的某个均值直接排名。'
        '2026属于S015原获准窗口，本轮没有访问S017的封存LITE2026数据。','',judgment['next_step'],'',
        ' · '.join(['[判断及限制](others/judgment.json)','[结果核验](others/result_validation.json)',
            '[原订单复现](others/order_reproduction.json)','[聚焦检查](others/checks.json)',
            '[逐事件标签](others/events.json.gz)','[信号事实](others/signal_facts.json.gz)',
            '[重抽样原值](others/bootstrap_draws.json.gz)','[运行前证据](others/pre_run_evidence.json)']), '']
    (WORK/'report.md').write_bytes('\n'.join(lines).encode('utf-8'))
    print('REPORT_RENDERED',flush=True)


if __name__=='__main__':
    main()
