"""Render the frozen comparisons and explicitly post-result researcher judgment."""
from study import WORK, read, digest
from mechanisms import NAMES, HORIZONS

LABELS = {'D': '超跌背景', 'R': '单独恢复', 'C': '超跌且恢复', 'D_NR': '超跌未恢复'}


def pct(value):
    return '无样本' if value is None else f'{100*value:.4f}%'


def mean(item, key='price'):
    if key == 'difference':
        value = item.get(key, {}).get('mean')
        return '无样本' if value is None else f'{100*value:.4f}个百分点'
    return pct(item.get(key, {}).get('mean'))


def ci(value):
    span = value['interval_95']
    if value['valid_replicates'] == 1:
        return '仅1次有效，区间不可解释'
    return '无有效抽样' if span is None else f'[{100*span[0]:.4f}, {100*span[1]:.4f}]'


def line(item):
    return f"{item['summary']['events']} / {item['summary']['price']['count']}|{mean(item['summary'])}|{mean(item['matched'], 'control')}|{mean(item['matched'], 'difference')}"


def main():
    a = read(WORK/'others/analysis.json')
    j = read(WORK/'others/judgment.json')
    v = read(WORK/'others/result_validation.json')
    if j['analysis_sha256'] != digest(WORK/'others/analysis.json') or v['status'] != 'PASS':
        raise ValueError('Unverified analysis or stale judgment')
    out = ['# EX021：超跌背景、恢复确认及持续性拆解', '', 'Status: COMPLETED', '',
        '## 研究结论', '', '本轮研究工作已完成；尚未形成完整策略原型，策略目标未达成。', '',
        j['conclusion'], '', j['interpretation'], '',
        '**最强反证与限制：** '+j['strongest_counterevidence'], '',
        '**下一步：** '+j['next_step'], '',
        '## 范围与样本', '',
        'S017阶段二，消耗追加额度1轮，累计13轮启动、12轮完成、1轮技术失败，剩7轮。'
        '3项新诊断表达D/R/D_NR，C为既有参考；0新账户、0参数搜索、0退出优化。'
        '阶段未推进，未使用2026行情绩效。', '',
        '仅重分析EX020认证的113950条标签、22790个决策时点和1760个交易日。'
        'LITE常规交易时段30m，2019-01-02至2025-12-31开发。固定1%买入限价溢价，单边0.1%费用。'
        '条件均在完成柱可见，下一段买入，N段后退出；无入场/无退出/截尾不记零或顺延。', '',
        'D：前柱收盘≤前柱SMA65−2×ATR13；R：本柱收盘>前柱最高；C=D且R；D_NR=D且非R。'
        'D、R、C存在交叠，四项不是独立发现。对照为同年月×计划入场美东时刻的全部普通机会（含目标本身）。', '',
        '## 主期限13柱：净机会与相对增量', '',
        '“完整”只计可买入且按期可退出的标签；“增量”为目标净均值减匹配普通机会均值，单位是百分点。'
        '去重按信号时间先后选，不依据未来成交或收益；仍不能保证样本独立。', '',
        '|表达|样本|触发/完整|自身净均值|匹配普通机会|增量|胜率|盈亏比|自身95%区间|增量95%区间|',
        '|---|---|---:|---:|---:|---:|---:|---:|---|---|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            x = a['horizons']['13']['signals'][name][mode]
            p, b = x['summary']['price'], x['bootstrap']['intervals']
            payoff = '无样本' if p.get('payoff_ratio') is None else f"{p['payoff_ratio']:.3f}"
            out.append(f"|{name} {LABELS[name]}|{mode}|{line(x)}|{pct(p.get('win_rate'))}|{payoff}|{ci(b['all_target_mean'])}|{ci(b['difference'])}|")
    out += ['', '## 同样超跌时，恢复确认是否有增量', '',
        'C对D_NR按原匹配格比较；对照使用全部D_NR。以下支持子集与全体C不同，不放宽匹配。'
        'R同时改变当前价格和入场时间，本表只反映条件关联，不能证明等待确认的因果收益。', '',
        '|期限|C样本|完整C|有对照C|无对照C|支持C净均值|D_NR匹配均值|差额|',
        '|---:|---|---:|---:|---:|---:|---:|---:|']
    for n in HORIZONS:
        for mode in ('raw', 'nonoverlap'):
            m = a['horizons'][str(n)]['confirmation'][mode]['matched']
            out.append(f"|{n}|{mode}|{m['all_target']['price']['count']}|{len(m['supported_indices'])}|{len(m['unmatched_indices'])}|{mean(m['supported_target'])}|{mean(m,'control')}|{mean(m,'difference')}|")
    out += ['', '|13柱样本|支持C自身95%区间|差额95%区间|差额有效抽样/1000|失去对照支持次数|空目标次数|',
        '|---|---|---|---:|---:|---:|']
    for mode in ('raw', 'nonoverlap'):
        b = a['horizons']['13']['confirmation'][mode]['bootstrap']
        out.append(f"|{mode}|{ci(b['intervals']['supported_target_mean'])}|{ci(b['intervals']['difference'])}|{b['intervals']['difference']['valid_replicates']}|{b['unsupported_control_replicates']}|{b['empty_target_replicates']}|")
    out += ['', '区间仅是有定义抽样的条件分位数；失去支持较多时不能用它宣称确认效果稳健显著。', '',
        '## 一次连续超跌段是否被重复计数', '',
        f"连续D段计数：{a['episode_counts']}。117段截至观察末尚无C，其中116段已结束、1段在样本末端尚未结束；未记零收益。首D与首C队列不同，不能直接相减作为确认收益。", '',
        '|每段首次事件|触发/完整|自身净均值|匹配普通机会|增量|自身95%区间|增量95%区间|',
        '|---|---:|---:|---:|---:|---|---|']
    for name, x in a['episode_results'].items():
        b = x['bootstrap']['intervals']
        out.append(f"|{name}|{line(x)}|{ci(b['all_target_mean'])}|{ci(b['difference'])}|")
    out += ['', '## 同一批入场的收益持续性', '',
        '以下先按130柱选取不重叠成员，再取五期限共同完整交集；所有期限使用相同入场。'
        '对照也固定为普通机会的共同完整交集。事后完整标签筛选只服务可比诊断，不能成为实盘入场条件。'
        '全部触发共同队列作为补充保存在analysis，不能只挑有利队列。', '',
        '|表达|预选/共同完整|排除|3柱净均值|13柱净均值|26柱净均值|65柱净均值|130柱净均值|',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in NAMES:
        x = a['duration'][name]['nonoverlap130']
        vals = '|'.join(mean(x['horizons'][str(n)]['summary']) for n in HORIZONS)
        out.append(f"|{name}|{len(x['preselected_indices'])}/{len(x['common_complete_indices'])}|{len(x['excluded'])}|{vals}|")
    out += ['', '|表达|持有延长|同本金净收益差|相对普通机会的差额|自身差95%区间|相对差95%区间|',
        '|---|---|---:|---:|---|---|']
    for name in NAMES:
        for key, x in a['duration'][name]['nonoverlap130']['increments'].items():
            b = x['bootstrap']['intervals']
            out.append(f"|{name}|{key}|{mean(x['summary'])}|{mean(x['matched'],'difference')}|{ci(b['all_target_mean'])}|{ci(b['difference'])}|")
    out += ['', '差额是同一入场本金下延长持有的收益变化，不是中途再开仓收益，不重扣买费；未搜索或验证最优退出。', '',
        '## 年际与集中性', '',
        '|表达|年份|13柱去重完整数|自身净均值|匹配增量|', '|---|---|---:|---:|---:|']
    for name in NAMES:
        for year, x in a['horizons']['13']['signals'][name]['nonoverlap']['years'].items():
            out.append(f"|{name}|{year}|{x['summary']['price']['count']}|{mean(x['summary'])}|{mean(x['matched'],'difference')}|")
    out += ['', '|表达/样本|正收益和最大年份占比|最大单事件占比|', '|---|---:|---:|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            c = a['horizons']['13']['signals'][name][mode]['concentration']
            out.append(f"|{name}/{mode}|{pct(c['largest_year_share'])}|{pct(c['largest_event_share'])}|")
    out += ['', '这些是事件正收益算术和的集中比例，原始事件可能重叠，不是账户利润贡献。完整月度分组保存在analysis。', '',
        '## 预定辅助期限', '', '|表达|期限|样本|触发/完整|自身净均值|匹配普通机会|增量|',
        '|---|---:|---|---:|---:|---:|---:|']
    for name in NAMES:
        for n in HORIZONS:
            for mode in ('raw', 'nonoverlap'):
                out.append(f"|{name}|{n}|{mode}|{line(a['horizons'][str(n)]['signals'][name][mode])}|")
    out += ['', '## 验证与证据边界', '',
        f"聚焦合成检查、独立结果核验通过。计算耗时{a['seconds']:.2f}秒，2个spawn进程，每进程原生线程1。"
        '1000次、20交易日移动块、seed17；全部比较共用日期权重，匹配控制均值在抽样内重估。'
        'C主期限及C对D_NR抽样作独立复算，其余抽样核对保存值、分位数与计数；未独立重建原OHLC成交路径。', '',
        '同一开发池已多次观察；区间为边际描述，未作多重选择校正、不保证覆盖全部长期依赖。'
        '事件价格收益忽略整仓资金、互斥机会和再投资，不能替代策略收益、回撤或交易次数验收。'
        '4×5基本结果格、确认对照、episode和同队列衍生诊断共同披露，不作独立发现累计。', '',
        *['- '+item for item in j['limits']], '',
        '[固定方案](protocols/design.md) · [授权](protocols/authorization.md) · '
        '[运行前正式引用](others/pre_run_evidence.json) · [完整结果](others/analysis.json) · '
        '[聚焦检查](others/checks.json) · [独立核验](others/result_validation.json) · '
        '[研究判断](others/judgment.json) · [正式发布回执](others/publication.json)', '']
    (WORK/'report.md').write_text('\n'.join(out), encoding='utf-8')
    print('REPORT_RENDERED', flush=True)


if __name__ == '__main__':
    main()
