"""Report final disjoint controls, preserving unsupported and undefined outcomes."""
from study import WORK, PARENTS, read, digest

MODES = {'raw': '全部触发', 'nonoverlap': '65柱去重'}
MATCHES = {'ordinary': '同月时刻', 'background_adjusted': '同月时刻及背景'}


def pct(value):
    return '无定义' if value is None else f'{100 * value:.4f}%'


def pp(value):
    return '无定义' if value is None else f'{100 * value:.4f}'


def interval(item, key):
    value = item['bootstrap']['intervals'][key]
    if value['valid_replicates'] < 2:
        return '无定义' if not value['valid_replicates'] else '仅1次有效，无法可靠解释'
    lo, hi = value['interval_95']
    return f'[{100 * lo:.4f}, {100 * hi:.4f}]'


def counts(item, key):
    value = item['bootstrap']['intervals'][key]
    return f"{value['valid_replicates']}/{value['undefined_replicates']}"


def status(summary):
    return '；'.join(f'{key}={value}' for key, value in sorted(summary['status'].items())) or '无事件'


def label(parent, mode, matching):
    main = '【唯一主读数】' if (parent, mode, matching) == ('S017-M007', 'nonoverlap', 'background_adjusted') else ''
    return f'{main}{parent}排除S017-M005/{MODES[mode]}/{MATCHES[matching]}'


def mean_row(name, x):
    m = x['matched']
    return (f"|{name}|{x['summary']['price']['count']}|{m['supported_target']['price']['count']}|"
            f"{len(m['unmatched_indices'])}|{pct(x['summary']['price'].get('mean'))}|"
            f"{pct(m['supported_target']['price'].get('mean'))}|{pct(m['control'].get('mean'))}|"
            f"{pp(m['difference'].get('mean'))}|")


def main():
    path = WORK/'others/analysis.json'
    a, j, v = read(path), read(WORK/'others/judgment.json'), read(WORK/'others/result_validation.json')
    if (v['status'] != 'PASS' or v['analysis_sha256'] != digest(path)
            or j['analysis_sha256'] != digest(path)):
        raise ValueError('Unverified results or stale judgment')
    if a['primary'] != {'parent': 'S017-M007', 'mode': 'nonoverlap', 'matching': 'background_adjusted', 'horizon': 65}:
        raise ValueError('Primary comparison changed')
    comparisons = []
    for parent in PARENTS:
        for mode in ('raw', 'nonoverlap'):
            for matching in MATCHES:
                x = a['results'][parent]['modes'][mode][matching]
                if x['matched']['support']['self_in_control_events'] != 0:
                    raise ValueError('Disjoint control contains target events')
                comparisons.append((label(parent, mode, matching), x))
    main_label = label('S017-M007', 'nonoverlap', 'background_adjusted')
    comparisons.sort(key=lambda pair: pair[0] != main_label)
    out = ['# EX026：最后一轮互斥条件对照', '', 'Status: COMPLETED', '',
           '## 结论与下一步', '', '本轮检验完成，条件拆解支线关闭；不代表完整策略达标或通过验收。', '',
           j['conclusion'], '', j['interpretation'], '', '**最强反证：** '+j['strongest_counterevidence'], '',
           '**下一步：** '+j['next_step'], '',
           '本轮后回到S017-M005原定义的最小账户原型主线；具体原型和固定退出须另行事前冻结。'
           '本轮没有运行账户、优化退出或启动另一轮拆解，不以证明每个条件必要性作为组合继续研究的硬门。', '',
           '## 固定机制与唯一主问题', '',
           't为已完成且可用的30分钟柱。TR=max(High−Low, abs(High−前Close), abs(Low−前Close))，'
           'ATR13为13个TR简单均值，SMA65为65个收盘价简单均值。共同底座是Close[t−1]<Open[t−1]且Close[t]>High[t−1]。', '',
           '|编号|原定义|', '|---|---|',
           '|S017-M005|共同底座；Volume[t−1]≥同槽过去20个实际交易日成交量中位数的1.5倍；TR[t−1]≤ATR13[t−2]。|',
           '|S017-M007|共同底座；TR[t−1]≤ATR13[t−2]，不要求放量。|',
           '|S017-M008|共同底座；Volume[t−1]≥同槽过去20个实际交易日成交量中位数的1.5倍，不要求窄幅。|',
           '|S017-M001|t及前12柱至少一次：前柱Close≤前柱SMA65−2×前柱ATR13。用于原近期超跌背景分层。|', '',
           '同槽按前柱美东RTH起始时刻计算，排除前柱所在日；半日缺槽不补零，夏令时按本地时刻匹配。'
           'ATR基准排除待判断前柱。四编号定义不变，集合差仅为诊断分组，不是新交易机制。', '',
           '|问题|固定目标|互斥控制|定位|', '|---|---|---|---|',
           '|放量提供什么信息|S017-M005|S017-M007排除全部S017-M005，即窄幅阴线收复但不放量|主问题|',
           '|窄幅提供什么信息|S017-M005|S017-M008排除全部S017-M005，即放量阴线收复但不窄幅|次要诊断|', '',
           '**唯一主读数：65柱去重的S017-M005，对S017-M007排除全部S017-M005，按同年月、计划入场美东时刻及S017-M001状态匹配。**'
           '其余七项是预定敏感性或次要诊断，好看的次要结果不替代主读数。', '',
           '两种目标样本×两种控制×两种匹配共八项比较。去重时选t后下一信号须严格晚于t+66；'
           '目标先选成员再看成交，不补选。控制始终保留互斥集合全部原始事件，不单独去重。'
           '两侧时间可能重叠，互斥不等于独立或因果。匹配格固定，不扩月、并槽、借背景或启用替代模型。', '',
           '## 覆盖：先看信号成员，再看完整标签', '',
           '|控制来源|父条件原始触发|排除S017-M005后的控制数|', '|---|---:|---:|']
    for parent in PARENTS:
        r = a['results'][parent]
        out.append(f"|{parent}|{r['parent_signals']}|{r['exclusive_controls']}|")
    out += ['', '|控制/目标样本/匹配|目标信号|有/无同格控制（不看标签）|目标完整|标签后支持/不支持|支持占完整目标|控制触发/完整|',
            '|---|---:|---:|---:|---:|---:|---:|']
    for name, x in comparisons:
        d, m, c = x['design'], x['matched'], x['control_summary']
        complete, supported = x['summary']['price']['count'], m['supported_target']['price']['count']
        out.append(f"|{name}|{len(d['target_indices'])}|{len(d['signal_supported_indices'])}/{len(d['signal_unmatched_indices'])}|"
                   f"{complete}|{supported}/{len(m['unmatched_indices'])}|{pct(supported/complete if complete else None)}|"
                   f"{c['events']}/{c['price']['count']}|")
    out += ['', '信号层支持只检查同格是否有控制信号；标签后支持还要求目标和控制有完整可用结果。'
           '未支持目标列表见[完整结果](others/analysis.json)的各比较design与matched；不得删掉这些事件后把支持子集冒充全部S017-M005。', '',
           '|控制/目标样本/匹配|总体|事件数|不同计划入场日|完整数|状态分布|',
           '|---|---|---:|---:|---:|---|']
    for name, x in comparisons:
        for population, s in (('全目标', x['summary']), ('支持目标子集', x['matched']['supported_target']),
                              ('全部互斥控制', x['control_summary'])):
            out.append(f"|{name}|{population}|{s['events']}|{s['days']}|{s['price']['count']}|{status(s)}|")
    out += ['', '## 八项固定比较', '',
           '匹配控制均值按支持目标所属格加权，不是全部控制事件的简单平均；不同支持子集之间的均值不可直接相减。', '',
           '|控制/目标样本/匹配|全目标完整|支持完整|无支持完整|全目标均值|支持目标均值|匹配控制均值|差额（百分点）|',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    out.extend(mean_row(name, x) for name, x in comparisons)
    out += ['', '|控制/目标样本/匹配|全目标95%描述区间（%）|支持目标95%描述区间（%）|差额有效抽样的95%条件分位区间（百分点）|全目标有效/未定义|支持目标有效/未定义|差额有效/未定义|',
           '|---|---|---|---|---:|---:|---:|']
    for name, x in comparisons:
        out.append(f"|{name}|{interval(x, 'all_target_mean')}|{interval(x, 'supported_target_mean')}|"
                   f"{interval(x, 'difference')}|{counts(x, 'all_target_mean')}|"
                   f"{counts(x, 'supported_target_mean')}|{counts(x, 'difference')}|")
    out += ['', '## 控制支持与未定义抽样', '',
           '|控制/目标样本/匹配|匹配格数|最低控制格数|仅1个控制的目标|格内全为目标|自身在控制中（应为0）|空目标抽样|丢失同格控制抽样|',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, x in comparisons:
        s, b = x['matched']['support'], x['bootstrap']
        minimum = s['minimum_control_count']
        out.append(f"|{name}|{s['cells']}|{minimum if minimum is not None else '无定义'}|{s['singleton_targets']}|"
                   f"{s['all_target_cell_events']}|{s['self_in_control_events']}|{b['empty_target_replicates']}|"
                   f"{b['unsupported_control_replicates']}|")
    out += ['', '移动块抽样可能保留某个目标，却没有抽到其同格的任何互斥控制；此时整次匹配差额未定义。'
           '这是稀疏控制在重抽样下无法支持比较，不是可以填零的收益，也不表示行情收益不存在。'
           '不删除失去控制的目标继续计算，不补零、不沿用原控制均值、不放宽匹配。'
           '无有效抽样就没有差额区间；仅少数有效时，区间只描述那些仍有控制支持的抽样，不能当作稳健结论。', '',
           '## 年际支持与差额', '',
           '|控制/目标样本/匹配及年份|全目标完整|支持完整|无支持完整|全目标均值|支持目标均值|匹配控制均值|差额（百分点）|',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, x in comparisons:
        out.extend(mean_row(name+'/'+year, y) for year, y in x['years'].items())
    out += ['', '|控制/目标样本/匹配|支持目标正收益算术和|最大单事件占比|最大年份占比|',
           '|---|---:|---:|---:|']
    for name, x in comparisons:
        c = x['supported_concentration']
        out.append(f"|{name}|{pct(c['positive_sum'])}|{pct(c['largest_event_share'])}|{pct(c['largest_year_share'])}|")
    out += ['', '集中度只针对支持目标的正收益算术和，不是账户利润贡献；逐年正收益和见完整结果。'
           '没有支持的年份不能由其他年份补齐，也不能把支持范围内的差额推广到全体信号。', '',
           '## 固定数据、费用与验证范围', '',
           f"LITE RTH原始30分钟；2018-11至12预热、2019-01-02至2025-12-31开发。"
           f"复用{a['eligible']}个已认证信号事实、原五期限113950条标签、{a['bootstrap']['sessions']}个计划入场交易日。"
           '本轮只新增65柱的八项比较；没有下载新数据、重建特征、回放成交或使用2026封存绩效。', '',
           't完成后仅在t+1一段尝试买入，限价Close[t]×1.01向下取整到0.01，严格穿越、零滑点；'
           '持有t+1至t+65，在t+66市价退出。单边费率0.1%，净收益=卖价×0.999/(买价×1.001)−1。'
           '无入场、无退出、未知路径及截尾分别保留，不记零、不顺延。', '',
           f"聚焦检查与独立结果核验通过，八项比较的全部抽样均独立复算。计算耗时{a['seconds']:.2f}秒；"
           f"{a['bootstrap']['block_sessions']}连续交易日移动块、{a['bootstrap']['replicates']}次、seed{a['bootstrap']['seed']}，"
           f"{a['bootstrap']['workers']}个spawn进程、原生线程{a['bootstrap']['native_threads']}。"
           '共享日期权重，每次重估控制；原机制身份、互斥成员、费用、分母、支持与区间均核验。'
           '原行情特征和成交仅认证来源，未重建；聚焦研究验证不是仓库全回归或策略验收。', '',
           '本轮0新入场表达、0账户、0参数搜索、0退出优化。额度累计启动18轮、完成17轮、技术失败1轮、剩2轮。'
           '拆解支线关闭，不追加拆解；后续账户原型须另行冻结，本轮未执行。', '',
           '区间为95%边际描述，未校正多重比较或多轮开发选择；所有比较共用已反复研究的开发池。'
           '不明确、跨零或无可靠差额区间，都不等于条件无用、组合无效或规则等价。', '',
           *['- '+s for s in j['limits']], '',
           '[固定方案](protocols/design.md) · [授权](protocols/authorization.md) · '
           '[运行前正式引用](others/pre_run_evidence.json) · [完整结果](others/analysis.json) · '
           '[聚焦检查](others/checks.json) · [独立核验](others/result_validation.json) · '
           '[研究判断](others/judgment.json) · [发布回执](others/publication.json)', '']
    (WORK/'report.md').write_bytes('\n'.join(out).encode('utf-8'))
    print('REPORT_RENDERED', flush=True)


if __name__ == '__main__':
    main()
