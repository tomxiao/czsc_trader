"""Render numbered entry evidence without inferring strategy acceptance."""
from study import WORK, NAMES, NEW_NAMES, HORIZONS, read, digest

LABELS = {
    'S017-M001': '近期超跌入场',
    'S017-M002': '回试前低不破入场',
    'S017-M003': '短跌半程收复入场',
    'S017-M004': '短跌波幅收窄后转强入场',
    'S017-M005': '放量窄幅下跌后收复入场',
}
MODES = {'raw': '全部触发', 'nonoverlap': '65柱去重', 'nonoverlap130': '130柱固定去重'}


def pct(value):
    return '无定义' if value is None else f'{100 * value:.4f}%'


def pp(value):
    return '无定义' if value is None else f'{100 * value:.4f}'


def own(item):
    return pct(item['summary']['price'].get('mean'))


def delta(item):
    return pp(item['matched']['difference'].get('mean'))


def ci(item, key):
    value = item['bootstrap']['intervals'][key]
    if value['valid_replicates'] < 2:
        return '有效抽样不足'
    lo, hi = value['interval_95']
    return f'[{100 * lo:.4f}, {100 * hi:.4f}]'


def draw_counts(item, key):
    value = item['bootstrap']['intervals'][key]
    return f"{value['valid_replicates']}/{value['undefined_replicates']}"


def comparison_table(out, comparisons):
    out += ['|编号/样本/对照|触发/完整|支持/无支持完整目标|自身净均值|支持目标均值|匹配控制均值|增量（百分点）|',
            '|---|---:|---:|---:|---:|---:|---:|']
    for label, x in comparisons:
        m = x['matched']
        out.append(f"|{label}|{x['summary']['events']}/{x['summary']['price']['count']}|"
                   f"{m['supported_target']['price']['count']}/{len(m['unmatched_indices'])}|{own(x)}|"
                   f"{pct(m['supported_target']['price'].get('mean'))}|{pct(m['control'].get('mean'))}|{delta(x)}|")
    out += ['', '|编号/样本/对照|自身95%区间（%）|增量95%区间（百分点）|自身有效/无定义抽样|增量有效/无定义抽样|',
            '|---|---|---|---:|---:|']
    for label, x in comparisons:
        out.append(f"|{label}|{ci(x, 'all_target_mean')}|{ci(x, 'difference')}|"
                   f"{draw_counts(x, 'all_target_mean')}|{draw_counts(x, 'difference')}|")
    out += ['']


def support_table(out, comparisons):
    out += ['|编号/样本/对照|匹配格数|最低控制格数|仅1个控制的目标|控制格全为目标|目标自身在控制中|空目标/无控制抽样|',
            '|---|---:|---:|---:|---:|---:|---:|']
    for label, x in comparisons:
        s, b = x['matched']['support'], x['bootstrap']
        minimum = s['minimum_control_count']
        out.append(f"|{label}|{s['cells']}|{minimum if minimum is not None else '无定义'}|"
                   f"{s['singleton_targets']}|{s['all_target_cell_events']}|{s['self_in_control_events']}|"
                   f"{b['empty_target_replicates']}/{b['unsupported_control_replicates']}|")
    out += ['']


def main():
    path = WORK/'others/analysis.json'
    a, j, v = read(path), read(WORK/'others/judgment.json'), read(WORK/'others/result_validation.json')
    if (j['analysis_sha256'] != digest(path) or v['analysis_sha256'] != digest(path)
            or v['status'] != 'PASS'):
        raise ValueError('Unverified results or stale judgment')
    primary = a['horizons']['65']['signals']
    out = ['# EX024：数字编号机制的数天修复入场竞争普查', '', 'Status: COMPLETED', '',
           '## 结论与下一步', '', '本轮入场普查完成；未形成完整策略，不代表策略目标达成或通过验收。', '',
           j['conclusion'], '', j['interpretation'], '', '**最强反证：** '+j['strongest_counterevidence'], '',
           '**下一步建议：** '+j['next_step'], '', '## 五项机制的完整定义', '',
           '编号只标识机制，不表示质量或排名。S017-M001是简单背景参照，S017-M002是旧研究参照；'
           '两者均未被认定为优质入场，也不是可投资业绩基准。S017-M003至S017-M005不要求S017-M001成立。', '',
           '以下t为当前已完成且可用的30分钟柱，收盘/开盘/最高/最低价对应Close/Open/High/Low。'
           'TR=max(High−Low, abs(High−前Close), abs(Low−前Close))，首根TR未知；ATR13是最近13个TR的简单均值，'
           'SMA65是最近65个收盘价简单均值。窗口按RTH柱序列计算，可以跨交易日。', '',
           '|编号|名称|完整条件|', '|---|---|---|',
           '|S017-M001|近期超跌入场|t−12至t至少一次满足：前柱Close≤前柱SMA65−2×前柱ATR13。|',
           '|S017-M002|回试前低不破入场|S017-M001成立；S=min Low[t−13..t−1]，p为S最后出现位置；'
           'p≤t−3；max High[p+1..t−1]≥S+ATR13[t−1]；S≤Low[t]≤S+0.5×ATR13[t−1]；Close[t]>High[t−1]。|',
           '|S017-M003|短跌半程收复入场|Close[t−4]−Close[t−1]≥ATR13[t−1]；Close[t]>(Close[t−4]+Close[t−1])/2。|',
           '|S017-M004|短跌波幅收窄后转强入场|t−3至t−1至少2柱收盘低于前柱收盘；Close[t−1]<Close[t−4]；'
           'TR[t−3]>TR[t−2]>TR[t−1]；Close[t]>High[t−1]。|',
           '|S017-M005|放量窄幅下跌后收复入场|Close[t−1]<Open[t−1]；Volume[t−1]≥历史同槽成交量中位数的1.5倍；'
           'TR[t−1]≤ATR13[t−2]；Close[t]>High[t−1]。|', '',
           'S017-M005的历史同槽中位数取前柱自身美东RTH起始时刻过去20个不同实际交易日的成交量，排除前柱所在日；'
           '半日缺槽不补零，夏令时按美东本地时刻匹配。波幅基准截至t−2。'
           '上述组合检验价格现象与后续机会的关联，不能证明真实卖压衰减、吸筹或单个条件的因果贡献。', '',
           '## 数据、执行与选择范围', '',
           f"LITE常规交易时段30分钟，2019-01-02至2025-12-31开发池，2018-11至12预热；"
           f"{a['eligible']}个共同决策时点、{a['bootstrap']['sessions']}个计划入场交易日。"
           '复用认证的113950条五期限执行标签，新形态只重读同一prepared行情；未使用2026封存绩效。', '',
           '主期限65柱（约五个常规交易日），辅助3/13/26/130柱。完成柱t后在t+1一段尝试单股限价买入，'
           '买价上限为Close[t]×1.01向下取整到0.01，严格穿越、零滑点；持有t+1至t+N，在t+N+1市价退出。'
           '每侧0.1%费用，净收益=卖价×0.999/(买价×1.001)−1。无成交、无法退出、未知路径和截尾分别保留，不补零或顺延。', '',
           '本轮消耗1轮额度：累计启动16轮、完成15轮、技术失败1轮、剩4轮。新增入场表达3、旧参照2，'
           '共25个机制×期限格及预定分层、持续性诊断；新增完整账户0、参数搜索0、退出优化0。'
           '数天跨度和新表达受已看过的开发池结果启发，属于同一轮后续选择历史，不是独立样本验证。', '',
           '## 主期限65柱：普通机会对照', '',
           '全部触发保留所有信号；65柱去重按时间先后预选，选中t后下个信号须严格晚于t+66，'
           '不看未来成交和收益，不因未成交补选。普通对照按同年月×计划入场美东时刻匹配，包含目标自身。'
           '各机制目标成员不同，不能直接将自身均值相减当作新机制改善；S017-M001、S017-M002仅作诊断参照，不作质量排名。', '']
    ordinary = [(f'{name}/{MODES[mode]}/普通', primary[name][mode])
                for name in NAMES for mode in ('raw', 'nonoverlap')]
    comparison_table(out, ordinary)
    out += ['|编号/样本|胜率|盈亏比|', '|---|---:|---:|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            p = primary[name][mode]['summary']['price']
            ratio = '无定义' if p.get('payoff_ratio') is None else f"{p['payoff_ratio']:.4f}"
            out.append(f"|{name}/{MODES[mode]}|{pct(p.get('win_rate'))}|{ratio}|")
    out += ['', '## 控制S017-M001背景状态后的增量', '',
           '在同年月×计划入场时刻匹配格中再加入S017-M001当时是否成立；这是统计分层，'
           '没有给新机制增加超跌过滤条件。S017-M001自身不计算机械为零的同状态新增信息。', '']
    adjusted = [(f'{name}/{MODES[mode]}/状态分层', primary[name][mode]['background_adjusted'])
                for name in NAMES[1:] for mode in ('raw', 'nonoverlap')]
    comparison_table(out, adjusted)
    out += ['## 新机制在S017-M001内、外的表现', '',
           '内、外分别取相同背景状态的普通机会；目标成员由既定信号切片，不按结果补选。'
           '切片强弱只能描述条件适用性，不能据此事后改写本轮入场规则。', '']
    slices = [(f"{name}/{MODES[mode]}/S017-M001{'内' if side == 'inside' else '外'}",
               primary[name][mode]['background_slices'][side])
              for name in NEW_NAMES for mode in ('raw', 'nonoverlap') for side in ('inside', 'outside')]
    comparison_table(out, slices)
    out += ['## 控制支持与抽样边界', '',
           '下表与前述支持/无支持目标数共同解释区间。自包含控制格会把部分差额机械压低；'
           '控制格全部是目标或只有一个目标时，不能据差额接近零宣称等价。'
           '有效/无定义抽样之和为1000；区间使用有定义抽样，不能掩盖空目标或无控制抽样。', '']
    support_table(out, ordinary + adjusted + slices)
    out += ['## 机会频率、年际与集中性', '',
           '|编号/样本|触发数|不同计划入场日|完整事件数|计划入场日占总体|状态分布|',
           '|---|---:|---:|---:|---:|---|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            s = primary[name][mode]['summary']
            statuses = '；'.join(f'{k}={v}' for k, v in sorted(s['status'].items()))
            out.append(f"|{name}/{MODES[mode]}|{s['events']}|{s['days']}|{s['price']['count']}|"
                       f"{pct(s['days']/a['bootstrap']['sessions'])}|{statuses}|")
    out += ['', '频率是信号机会，不是账户闭合交易频率；去重也不能保证事件独立。'
           '既定账户频率目标与买入并持有业绩基准本轮均未验收。', '',
           '|编号/样本|年份|触发/完整|不同计划入场日|自身净均值|普通增量（百分点）|',
           '|---|---|---:|---:|---:|---:|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            for year, x in primary[name][mode]['years'].items():
                s = x['summary']
                out.append(f"|{name}/{MODES[mode]}|{year}|{s['events']}/{s['price']['count']}|{s['days']}|{own(x)}|{delta(x)}|")
    out += ['', '|编号/样本|有触发月份/总月份|均值正/负/零月份|最大单事件占正收益和|最大年份占正收益和|',
           '|---|---:|---:|---:|---:|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            x = primary[name][mode]
            months = x['months']
            means = [m['summary']['price']['mean'] for m in months.values() if m['summary']['price']['count']]
            positive, negative, zero = (sum(v > 0 for v in means), sum(v < 0 for v in means), sum(v == 0 for v in means))
            c = x['concentration']
            active = sum(m['summary']['events'] > 0 for m in months.values())
            out.append(f"|{name}/{MODES[mode]}|{active}/{len(months)}|{positive}/{negative}/{zero}|"
                       f"{pct(c['largest_event_share'])}|{pct(c['largest_year_share'])}|")
    out += ['', '无完整事件的月份不计入均值正负零；全部月份的事件数、状态及对照明细见'
           '[完整结果](others/analysis.json)的horizons/65/signals/<编号>/<样本>/months。'
           '集中度以事件正收益算术和为分母，不是账户净利润贡献；重叠信号不能当独立收益叠加。', '',
           '## 全部固定辅助期限', '',
           '|编号|期限（柱）|样本|触发/完整|自身净均值|普通增量（百分点）|',
           '|---|---:|---|---:|---:|---:|']
    for name in NAMES:
        for n in HORIZONS:
            if n == 65:
                continue
            for mode in ('raw', 'nonoverlap'):
                x = a['horizons'][str(n)]['signals'][name][mode]
                mode_label = '全部触发' if mode == 'raw' else f'{n}柱去重'
                out.append(f"|{name}|{n}|{mode_label}|{x['summary']['events']}/{x['summary']['price']['count']}|{own(x)}|{delta(x)}|")
    out += ['', '各期限的去重成员可能不同，不能仅由上表均值差解释延长持有的收益；以下固定队列解决成员可比问题。', '',
           '## 固定共同队列的持续性', '',
           '原始队列或按最大130柱预选去重成员，再取五期限共同完整交集；控制也取共同完整交集。'
           '先预选再看标签，不补选。完整性交集是事后可用性诊断，不能作为实盘入场筛选。', '',
           '|编号/队列|预选数|共同完整数|排除数|', '|---|---:|---:|---:|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap130'):
            x = a['duration'][name][mode]
            out.append(f"|{name}/{MODES[mode]}|{len(x['preselected_indices'])}|{len(x['common_complete_indices'])}|{len(x['excluded'])}|")
    out += ['', '排除成员及逐期限原因见[完整结果](others/analysis.json)的duration；以下同时披露每个固定期限和同本金增量。', '']
    duration = []
    for name in NAMES:
        for mode in ('raw', 'nonoverlap130'):
            x = a['duration'][name][mode]
            duration += [(f'{name}/{MODES[mode]}/{n}柱', x['horizons'][str(n)]) for n in HORIZONS]
            duration += [(f"{name}/{MODES[mode]}/{key.replace('-', '→')}柱增量", item)
                         for key, item in x['increments'].items()]
    comparison_table(out, duration)
    out += ['增量行的自身读数是同初始本金收益差，单位应读作百分点；不是中途重新买入的收益，'
           '不重复扣买费。所有期限均预先指定，期限峰值不代表最优退出。', '',
           '## 原始信号交叠', '', '|编号|'+'|'.join(NAMES)+'|', '|---|'+'---:|'*len(NAMES)]
    for name in NAMES:
        out.append('|'+name+'|'+'|'.join(str(a['overlap'][name][other]) for other in NAMES)+'|')
    out += ['', '对角线为原始触发数，非对角线为同一决策时点共同触发数；不是独立机会或账户持仓数。', '',
           '## 验证与证据边界', '',
           f"聚焦检查、独立结果核验已通过。研究计算耗时{a['seconds']:.2f}秒；"
           f"{a['bootstrap']['workers']}个spawn进程，每进程原生线程{a['bootstrap']['native_threads']}。"
           f"{a['bootstrap']['block_sessions']}连续交易日移动块、{a['bootstrap']['replicates']}次、seed{a['bootstrap']['seed']}，"
           '共享日期权重并逐次重估控制均值。新三项主期限去重的普通/状态分层6组抽样独立复算；'
           '其余保存抽样核对分位数、计数及成员。原成交标签身份及费用核验，本轮未重建逐笔成交。', '',
           '区间是95%边际描述，未作多重比较修正，不消除重复查看开发池、挑选表达与主期限的选择偏差；'
           '没有在看到结果后追加60日块检查。合成及研究结果聚焦验证不等于仓库全回归、策略验收或生产准入。', '',
           *['- '+s for s in j['limits']], '',
           '[固定方案](protocols/design.md) · [授权](protocols/authorization.md) · '
           '[编号快照](protocols/mechanism_index.json) · [运行前正式引用](others/pre_run_evidence.json) · '
           '[完整结果](others/analysis.json) · [聚焦检查](others/checks.json) · '
           '[独立核验](others/result_validation.json) · [研究判断](others/judgment.json) · [发布回执](others/publication.json)', '']
    (WORK/'report.md').write_bytes('\n'.join(out).encode('utf-8'))
    print('REPORT_RENDERED', flush=True)


if __name__ == '__main__':
    main()
