"""Render all preregistered competitors and post-result research judgment."""
from study import WORK, NAMES, NEW_NAMES, HORIZONS, read, digest

LABELS = {'B': '近期超跌背景', 'C': '旧恢复确认', 'F': '跌破收回', 'T': '回试不破', 'H': '低点抬高'}


def pct(value):
    return '无样本' if value is None else f'{100*value:.4f}%'


def pp(value):
    return '无样本' if value is None else f'{100*value:.4f}'


def own(item):
    return pct(item['summary']['price'].get('mean'))


def delta(item):
    return pp(item['matched']['difference'].get('mean'))


def ci(item, key):
    value = item['bootstrap']['intervals'][key]
    if value['valid_replicates'] < 2:
        return '可用抽样不足'
    lo, hi = value['interval_95']
    return f'[{100*lo:.4f}, {100*hi:.4f}]'


def main():
    a = read(WORK/'others/analysis.json')
    j = read(WORK/'others/judgment.json')
    v = read(WORK/'others/result_validation.json')
    if j['analysis_sha256'] != digest(WORK/'others/analysis.json') or v['status'] != 'PASS':
        raise ValueError('Unverified results or stale judgment')
    out = ['# EX022：跌不下去的三类入场假设普查', '', 'Status: COMPLETED', '',
        '## 结论与下一步', '', '本轮研究工作完成；事件诊断不代表完整策略目标达成。', '',
        j['conclusion'], '', j['interpretation'], '', '**最强反证：** '+j['strongest_counterevidence'], '',
        '**下一步建议：** '+j['next_step'], '', '## 研究问题与固定范围', '',
        'F问“跌破后迅速收回来是否有用”；T问“反弹后再次回试前低而不破是否有用”；'
        'H问“近期低点抬高且向上突破短区间是否有用”。三者共同要求最近13柱内出现过超跌，'
        '分别与全部普通机会、近期超跌背景B比较；旧C作为参考。B是本轮新背景，不能冒称旧轮已验证。'
        '这些价格条件不能证明实际卖压消失。', '',
        '主期限13柱，辅助3/26/65/130。只用LITE常规交易时段30m、2019-01-02至2025-12-31开发池，'
        '22790个决策时点、1760个入场交易日；未使用2026封存行情绩效。复用EX020认证的113950条标签，'
        '新形态使用同一prepared数据；新标签回放0、完整账户0、搜索0。固定1%限价买入溢价、单边0.1%费用。', '',
        '本轮消耗1轮额度：追加20轮中累计启动14轮、完成13轮、技术失败1轮，剩6轮。'
        '新增3个主表达及1个背景表达，旧C参考；25个信号×期限格、背景对照、段内首次及同队列诊断共同披露，'
        '不当作独立发现。', '',
        '## 主期限13柱', '',
        'raw为全部触发；nonoverlap为按时间先后减少持有区间重叠。预选不看未来成交或收益。'
        '“完整”仅计按固定合同成功进入并按期退出；其他状态单列，未记零。'
        '所有增量单位为百分点；自身区间单位为百分比，增量区间单位为百分点。', '',
        '|表达|样本|触发/完整|自身净均值|胜率|盈亏比|相对普通机会|相对B|自身95%区间|普通增量95%区间|B增量95%区间|',
        '|---|---|---:|---:|---:|---:|---:|---:|---|---|---|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            x = a['horizons']['13']['signals'][name][mode]
            p = x['summary']['price']
            ratio = '无样本' if p.get('payoff_ratio') is None else f"{p['payoff_ratio']:.3f}"
            parent = x.get('background')
            out.append(f"|{name} {LABELS[name]}|{mode}|{x['summary']['events']}/{p['count']}|{own(x)}|{pct(p.get('win_rate'))}|{ratio}|{delta(x)}|{delta(parent) if parent else '—'}|{ci(x,'all_target_mean')}|{ci(x,'difference')}|{ci(parent,'difference') if parent else '—'}|")
    out += ['', '## 对照支持与信号交叠', '',
        '匹配采用同年月×计划入场美东时刻。普通机会包含目标自身；B对照也包含其子集目标。'
        '只说明条件关联，不代表因果收益。自包含会把某些控制格的差额机械压为零。', '',
        '|表达/样本|B对照最低格样本数|仅1个控制的目标数|控制格全是目标的事件数|目标自身在控制中的事件数|B差额有效抽样/1000|',
        '|---|---:|---:|---:|---:|---:|']
    for name in ('C', *NEW_NAMES):
        for mode in ('raw', 'nonoverlap'):
            x = a['horizons']['13']['signals'][name][mode]['background']
            s = x['matched']['support']
            out.append(f"|{name}/{mode}|{s['minimum_control_count']}|{s['singleton_targets']}|{s['all_target_cell_events']}|{s['self_in_control_events']}|{x['bootstrap']['intervals']['difference']['valid_replicates']}|")
    out += ['', '|信号交叠|'+'|'.join(NAMES)+'|', '|---|'+'---:|'*len(NAMES)]
    for name in NAMES:
        out.append('|'+name+'|'+'|'.join(str(a['overlap'][name][other]) for other in NAMES)+'|')
    out += ['', 'F与T互斥，H可重叠；不能把重叠事件重复计算为独立机会。', '',
        '## 每个近期超跌段仅取首次信号', '',
        'B连续为真的一段只是诊断分组，不是独立底部周期。首端左删失段排除；末端右删失段中尚未出现信号，'
        '不能说完整段不会出现。各组首次事件时点和成员不同，不能直接相减当作确认效果。', '',
        f"段计数：共{a['segment_counts']['total']}段，可用{a['segment_counts']['usable']}段，"
        f"左删失{a['segment_counts']['left_censored']}段、右删失{a['segment_counts']['right_censored']}段。", '',
        '|表达|有信号段/截至观察末无信号段|首次事件/完整|自身净均值|相对普通机会|相对B|自身95%区间|B增量95%区间|',
        '|---|---:|---:|---:|---:|---:|---|---|']
    for name in NAMES:
        x = a['first'][name]
        parent = x.get('background')
        out.append(f"|{name}|{a['segment_counts']['with_signal'][name]}/{a['segment_counts']['without_signal'][name]}|{x['summary']['events']}/{x['summary']['price']['count']}|{own(x)}|{delta(x)}|{delta(parent) if parent else '—'}|{ci(x,'all_target_mean')}|{ci(parent,'difference') if parent else '—'}|")
    out += ['', '## 同一入场队列的持续性', '',
        '先用130柱去重固定成员，再取五期限共同完整交集，不重新补选；控制也固定共同完整。'
        '完整性交集是事后可用性筛选，不能成为实盘入场条件。所有原始成员、剔除原因和全触发共同队列见完整结果。', '',
        '|表达/队列|预选/共同完整|3柱净均值|13柱净均值|26柱净均值|65柱净均值|130柱净均值|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap130'):
            x = a['duration'][name][mode]
            values = '|'.join(own(x['horizons'][str(n)]) for n in HORIZONS)
            out.append(f"|{name}/{mode}|{len(x['preselected_indices'])}/{len(x['common_complete_indices'])}|{values}|")
    out += ['', '|表达（130去重队列）|延长持有|同本金收益差|相对普通机会差额|自身差95%区间|相对差95%区间|',
        '|---|---|---:|---:|---|---|']
    for name in NAMES:
        for key, x in a['duration'][name]['nonoverlap130']['increments'].items():
            out.append(f"|{name}|{key}|{own(x)}|{delta(x)}|{ci(x,'all_target_mean')}|{ci(x,'difference')}|")
    out += ['', '差额以最初入场本金计算，不是中途再开仓收益，不重复扣买费；期限峰值不代表最优退出。', '',
        '## 年际、集中性与辅助期限', '',
        '|表达（13柱去重）|年份|完整数|自身净均值|相对普通机会|', '|---|---|---:|---:|---:|']
    for name in NAMES:
        for year, x in a['horizons']['13']['signals'][name]['nonoverlap']['years'].items():
            out.append(f"|{name}|{year}|{x['summary']['price']['count']}|{own(x)}|{delta(x)}|")
    out += ['', '|表达/样本|正收益算术和最大年份占比|最大单事件占比|', '|---|---:|---:|']
    for name in NAMES:
        for mode in ('raw', 'nonoverlap'):
            c = a['horizons']['13']['signals'][name][mode]['concentration']
            out.append(f"|{name}/{mode}|{pct(c['largest_year_share'])}|{pct(c['largest_event_share'])}|")
    out += ['', '上述比例不是账户净利润贡献。完整年/月、首次事件分组、交易未完成状态见analysis。', '',
        '|表达|期限|样本|触发/完整|自身净均值|相对普通机会|相对B|', '|---|---:|---|---:|---:|---:|---:|']
    for name in NAMES:
        for n in HORIZONS:
            for mode in ('raw', 'nonoverlap'):
                x = a['horizons'][str(n)]['signals'][name][mode]
                parent = x.get('background')
                out.append(f"|{name}|{n}|{mode}|{x['summary']['events']}/{x['summary']['price']['count']}|{own(x)}|{delta(x)}|{delta(parent) if parent else '—'}|")
    out += ['', '## 验证与证据边界', '',
        f"聚焦合成检查、独立结果核验已通过；研究计算{a['seconds']:.2f}秒，2个spawn进程、每进程原生线程1。"
        '1000次20交易日移动块，seed17，共享日期权重并重估控制均值。'
        '新F/T/H主期限去重对普通机会及B的6组重抽样作独立复算；其余抽样保留并核对区间与计数。', '',
        *['- '+s for s in j['limits']], '',
        '[固定方案](protocols/design.md) · [授权](protocols/authorization.md) · '
        '[运行前正式引用](others/pre_run_evidence.json) · [完整结果](others/analysis.json) · '
        '[聚焦检查](others/checks.json) · [独立核验](others/result_validation.json) · '
        '[研究判断](others/judgment.json) · [发布回执](others/publication.json)', '']
    (WORK/'report.md').write_bytes(('\n'.join(out)).encode('utf-8'))
    print('REPORT_RENDERED', flush=True)


if __name__ == '__main__':
    main()
