"""Report fixed-entry evidence, including positive findings and counterevidence."""
from study import WORK, COHORTS, METRICS, KEY_METRICS, read, digest

COHORT_LABELS = {'nonoverlap130': '主45去重队列', 'raw': '原始共同队列', 'first_B': 'B段首次T'}
CONTROL_LABELS = {'ordinary': '普通机会', 'B': '近期超跌B', 'C': '旧恢复C'}


def pct(value):
    return '无样本' if value is None else f'{100*value:.4f}%'


def pp(value):
    return '无样本' if value is None else f'{100*value:.4f}'


def own(item):
    return pct(item['summary']['price'].get('mean'))


def delta(item):
    return pp(item['matched']['difference'].get('mean'))


def ci(item, key, block=20):
    value = item['bootstrap' if block == 20 else 'bootstrap60']['intervals'][key]
    if value['valid_replicates'] < 2:
        return '有效抽样不足'
    lo, hi = value['interval_95']
    return f'[{100*lo:.4f}, {100*hi:.4f}]'


def main():
    a = read(WORK/'others/analysis.json')
    j = read(WORK/'others/judgment.json')
    v = read(WORK/'others/result_validation.json')
    if j['analysis_sha256'] != digest(WORK/'others/analysis.json') or v['status'] != 'PASS':
        raise ValueError('Unverified analysis or stale judgment')
    out = ['# EX023：回试前低不破后的数天修复补证', '', 'Status: COMPLETED', '',
        '## 研究结论', '', '本轮补证工作完成；未形成完整策略，策略目标未达成。', '',
        j['conclusion'], '', j['interpretation'], '', '**最强反证与限制：** '+j['strongest_counterevidence'], '',
        '**下一步建议：** '+j['next_step'], '', '## 固定范围与选择历史', '',
        'T入场保持EX022全部定义和源码身份不变：近期曾超跌、先离开前低，再回试前低附近而不破，并在完成柱收盘确认。'
        '本轮没有调阈值、增删入场条件、搜索持有期或优化退出。使用已认证的旧信号与五期限价格标签，不重新下载行情或回放。', '',
        'LITE RTH 30m，2019-01-02至2025-12-31开发，2018-11至12预热；22790个共同决策时点、1760交易日，未用2026行情绩效。'
        '固定1%买入限价溢价、每侧0.1%费用，下一段单股限价买入，N段后市价退出。无成交/无法退出/未知路径/截尾不补零。', '',
        '26→65的关注来自已看过的EX022辅助结果，属于后续选择，不能称独立验证或改写旧主期限。'
        '本轮共同关键读数是65柱总净收益与26→65同初始本金差额；差额不是中途再买入的收益，不重复扣买费。', '',
        '消耗1轮额度：累计15轮启动、14轮完成、1轮技术失败，剩5轮。新增入场表达0、完整账户0、参数搜索0、退出优化0。', '',
        '## 固定队列与机会频率', '',
        '|队列|预选事件|共同完整|排除数|', '|---|---:|---:|---:|']
    for name in COHORTS:
        x = a['cohorts'][name]
        out.append(f"|{COHORT_LABELS[name]}|{len(x['preselected_indices'])}|{len(x['common_complete_indices'])}|{len(x['excluded'])}|")
    out += ['', '共同完整要求原3/13/26/65/130标签均可用；先选信号和去重成员，再取交集，不补选。'
        '它是事后可用性条件，不能作为实盘入场筛选。原始67事件中1次因已知中断没有入场，不能记零。'
        '主45成员与原始66成员逐项复现EX022。三种队列大量重叠，不是独立验证。', '',
        f"原始T有{a['frequency']['signals']}次触发，分布于{a['frequency']['planned_entry_days']}个计划入场日、"
        f"{a['frequency']['segments_with_T']}个连续B段。计划入场状态：{a['frequency']['entry_status']}。", '',
        '|计划入场年份|原始信号数|不同计划入场日|', '|---|---:|---:|']
    for year, x in a['frequency']['years'].items():
        out.append(f"|{year}|{x['signals']}|{x['planned_entry_days']}|")
    out += ['', '信号机会数、独立样本数和账户闭合交易数分别判断。'
        '现有[目标约定](../../deliveries/MANDATE/2/report.md)由[MANDATE/3](../../deliveries/MANDATE/3/report.md)确认，'
        '要求滚动60交易日闭合中位数≥6且至少90%窗口≥3笔；T每年只有5至13次原始触发，作为唯一入口的频率适配度较弱。'
        '本轮未跑账户，不用信号计数替代正式闭合频率验收。', '',
        '## 主45队列：总机会与背景之外的增量', '',
        '所有控制均取五期限共同完整交集，按同年月×美东计划入场时刻匹配。控制包含目标自身；'
        'C只支持44个T，以下支持子集均值单列，不能与45事件对B的差额直接相减。增量单位为百分点。', '',
        '|读数|控制|全体T净均值/差额|支持T数|支持T均值|控制均值|匹配增量|',
        '|---|---|---:|---:|---:|---:|---:|']
    for metric in KEY_METRICS:
        for control, x in a['results']['nonoverlap130']['metrics'][metric]['comparisons'].items():
            m = x['matched']
            out.append(f"|{metric}|{CONTROL_LABELS[control]}|{own(x)}|{m['supported_target']['price']['count']}|{pct(m['supported_target']['price'].get('mean'))}|{pct(m['control'].get('mean'))}|{delta(x)}|")
    out += ['', '|主65柱控制|支持T数|无支持T数|最小控制格事件数|仅1个控制的目标数|控制格全为目标的事件数|',
        '|---|---:|---:|---:|---:|---:|']
    for control, x in a['results']['nonoverlap130']['metrics']['65']['comparisons'].items():
        m = x['matched']
        s = m['support']
        out.append(f"|{CONTROL_LABELS[control]}|{m['supported_target']['price']['count']}|{len(m['unmatched_indices'])}|{s['minimum_control_count']}|{s['singleton_targets']}|{s['all_target_cell_events']}|")
    out += ['', 'C的部分控制格仅包含目标自身，差额机械为零；不能据均值差很小宣称T与C等价。', '',
        '|读数|控制|20日块自身区间|20日块增量区间|增量有效/1000|60日块自身区间|60日块增量区间|增量有效/1000|',
        '|---|---|---|---|---:|---|---|---:|']
    for metric in KEY_METRICS:
        for control, x in a['results']['nonoverlap130']['metrics'][metric]['comparisons'].items():
            out.append(f"|{metric}|{CONTROL_LABELS[control]}|{ci(x,'all_target_mean')}|{ci(x,'difference')}|{x['bootstrap']['intervals']['difference']['valid_replicates']}|{ci(x,'all_target_mean',60)}|{ci(x,'difference',60)}|{x['bootstrap60']['intervals']['difference']['valid_replicates']}|")
    out += ['', '自身区间覆盖全体45事件；C匹配差只覆盖其44个支持事件，有效重抽样不足1000的差额区间是有定义抽样的条件分位数。'
        '区间为95%边际描述，未作多重选择修正。60日块检查部分较长依赖，不能让重复开发样本变成独立验证。', '',
        '## 年际及删除一个年份的影响', '',
        '|读数|年份|事件数|自身均值|对普通增量|对B增量|对C增量|C支持数|',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for metric in KEY_METRICS:
        for year, cc in a['results']['nonoverlap130']['stress'][metric]['years'].items():
            out.append(f"|{metric}|{year}|{cc['ordinary']['summary']['price']['count']}|{own(cc['ordinary'])}|{delta(cc['ordinary'])}|{delta(cc['B'])}|{delta(cc['C'])}|{cc['C']['matched']['supported_target']['price']['count']}|")
    out += ['', '|读数|删除年份|剩余事件数|自身均值|对普通增量|对B增量|对C增量|',
        '|---|---|---:|---:|---:|---:|---:|']
    for metric in KEY_METRICS:
        for year, cc in a['results']['nonoverlap130']['stress'][metric]['leave_year_out'].items():
            out.append(f"|{metric}|{year}|{cc['ordinary']['summary']['price']['count']}|{own(cc['ordinary'])}|{delta(cc['ordinary'])}|{delta(cc['B'])}|{delta(cc['C'])}|")
    out += ['', '上述是固定历史样本的影响诊断，不是独立验证；每年仅3至9个主队列事件，不能据年度正负保证跨状态稳定。', '',
        '## 少数大盈利事件的影响', '',
        '每项读数按其自身正贡献排序，删除最大的1或3个目标事件；控制总体保持原样。'
        '删除名单由未来结果决定，只用于影响诊断，不能当入场条件或可执行策略。', '',
        '|读数|删去数量|删去事件（计划入场日期/索引）|剩余自身均值|对普通增量|对B增量|对C增量|',
        '|---|---:|---|---:|---:|---:|---:|']
    for metric in KEY_METRICS:
        for count, x in a['results']['nonoverlap130']['stress'][metric]['drop_positive_events'].items():
            cc = x['comparisons']
            removed = '、'.join(f"{r['date']}/{r['i']}" for r in x['removed'])
            out.append(f"|{metric}|{count}|{removed}|{own(cc['ordinary'])}|{delta(cc['ordinary'])}|{delta(cc['B'])}|{delta(cc['C'])}|")
    out += ['', '|队列|读数|正贡献事件|最大事件占正收益和|前三事件占正收益和|最大年份占正收益和|',
        '|---|---|---:|---:|---:|---:|']
    for cohort in COHORTS:
        for metric in KEY_METRICS:
            c = a['results'][cohort]['metrics'][metric]['concentration']
            out.append(f"|{COHORT_LABELS[cohort]}|{metric}|{c['positive_events']}|{pct(c['largest_event_positive_share'])}|{pct(c['top3_positive_share'])}|{pct(c['largest_year_positive_share'])}|")
    out += ['', '贡献比例以事件正收益算术和为分母，不是账户净利润贡献。净和、正负和和各年明细保存在完整结果。', '',
        '## 原始与段内首次队列', '',
        '|队列|读数|控制|全体事件|支持事件|自身均值|匹配增量|自身20日块区间|增量区间|',
        '|---|---|---|---:|---:|---:|---:|---|---|']
    for cohort in ('raw', 'first_B'):
        for metric in KEY_METRICS:
            for control, x in a['results'][cohort]['metrics'][metric]['comparisons'].items():
                out.append(f"|{COHORT_LABELS[cohort]}|{metric}|{CONTROL_LABELS[control]}|{x['summary']['price']['count']}|{x['matched']['supported_target']['price']['count']}|{own(x)}|{delta(x)}|{ci(x,'all_target_mean')}|{ci(x,'difference')}|")
    out += ['', '## 固定期限边界', '', '|队列|读数|自身均值|对普通增量|对B增量|对C增量|', '|---|---|---:|---:|---:|---:|']
    for cohort in COHORTS:
        for metric in METRICS:
            cc = a['results'][cohort]['metrics'][metric]['comparisons']
            out.append(f"|{COHORT_LABELS[cohort]}|{metric}|{own(cc['ordinary'])}|{delta(cc['ordinary'])}|{delta(cc['B'])}|{delta(cc['C'])}|")
    out += ['', '13/26/65/130为固定退出标签，26-65/65-130为同本金差额；没有搜索最优期限。', '',
        '## 验证、限制与材料', '',
        f"聚焦检查、独立结果核验通过。研究计算耗时{a['seconds']:.2f}秒，2个spawn进程、每进程原生线程1；"
        '20/60日移动块各1000次、seed17。主队列两个关键读数×三个控制×两个块长的12组抽样已独立复算，'
        '其余保存抽样核对分位数与计数。', '',
        *['- '+s for s in j['limits']], '',
        '[固定方案](protocols/design.md) · [授权](protocols/authorization.md) · '
        '[运行前正式引用](others/pre_run_evidence.json) · [完整结果](others/analysis.json) · '
        '[聚焦检查](others/checks.json) · [独立核验](others/result_validation.json) · '
        '[研究判断](others/judgment.json) · [发布回执](others/publication.json)', '']
    (WORK/'report.md').write_bytes('\n'.join(out).encode('utf-8'))
    print('REPORT_RENDERED', flush=True)


if __name__ == '__main__':
    main()
