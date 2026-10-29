"""Render all frozen comparisons and the researcher's post-result judgment."""
from study import WORK,PRIMARY,HORIZONS,read,save,digest

LABELS={'A':'突破启动','B':'回调恢复','C':'超跌修复','AC':'收缩后突破','AV':'放量突破','PAT':'旧PAT参考'}


def pct(x):
    return '无样本' if x is None else f'{100*x:.4f}%'


def number(x):
    return '无样本' if x is None else f'{x:.3f}'


def interval(value):
    limits=value['interval_95']
    return '无有效重抽样' if limits is None else f'[{100*limits[0]:.4f}, {100*limits[1]:.4f}]'


def main():
    a=read(WORK/'others/analysis.json')
    validation=read(WORK/'others/result_validation.json')
    c=a['horizons']['13']['signals']['C']
    year2025=c['years']['2025']['raw']['price']
    net_share=year2025['count']*year2025['mean']/(c['raw']['price']['count']*c['raw']['price']['mean'])
    judgment={
        'analysis_sha256':digest(WORK/'others/analysis.json'),'work_complete':True,'strategy_goals_met':False,
        'conclusion':'本轮5种入场表达竞争诊断完成。超跌修复C在事前主期限13柱显示相对同月同时刻一般机会的正增量，原始和减少重叠方向一致，值得优先补充入场机制证据；但减少重叠后自身净均值只有0.0616%，描述区间跨零，尚不能宣布已找到足够可交易的入场信号。A/B/AC/AV的主期限匹配增量均负，旧PAT结论未改变。本轮没有形成完整原型或阶段推进依据。',
        'strongest_counterevidence':'C原始主期限1366个完整标签均值0.3182%，减少重叠后436个降至0.0616%，后者95%描述区间[-0.2893%,0.3724%]；2025年仅144个原始完整标签，却约占全期单笔标签净收益合计63.5%。2022年C绝对均值仍负，相对普通机会为正不能替代可赚钱的多头机会。130柱辅助期限C去重匹配差转负；不能事后选65柱重新宣布主期限胜出。',
        'interpretation':'当前固定表达下，等待近期高点突破未比相同时间背景下的一般机会更好；相对线索来自下跌过度后的恢复。它可能反映短期修复，也可能只是超跌背景本身；本轮不能把增量归因于恢复确认，亦不能推翻所有趋势跟踪。',
        'next_step':'建议继续阶段二，优先用下一轮固定对照拆解C：在同一超跌定义下比较不要求恢复确认与当前恢复确认，检查优势来自超跌背景还是确认动作，并显式检查同一段下跌中的重复触发影响。保持13柱标签、既有费用及执行合同，不优化退出、不搜索阈值。取得更清楚的绝对机会与入场增量依据后再安排退出研究。下一轮尚未执行，等待用户决定。',
        'next_hypothesis_status':'POST_RESULT_PROPOSAL_NOT_TESTED',
        'limits':['2019—2025开发池已多次观察；本轮冻结发生在历史开发经验之后，不是独立验证。未读2026行情绩效。',
            '5个新表达及5期限产生25个新结果格，连同旧PAT为30格；有共同样本、嵌套条件及选择偏差。',
            '20交易日块的边际区间未作多重选择校正，不能保证覆盖长期依赖或未来状态变化。',
            '匹配是历史描述控制，不是随机试验；包括目标自身，不能消除所有状态差异。AC/AV的A对照尤其稀疏。',
            '去重集合按信号先后固定，不等于独立样本或实际账户；单股价格标签不含资金再投资与机会互斥。',
            'verify核对已保存bootstrap抽样值与分位数，未再次独立重算全部抽样；旧标签逐行复现发生在run内。'],
        'quota':{'initiated':12,'completed':11,'failed':1,'remaining':8},
        'new_entry_expressions':5,'new_strategy_configurations':0,'new_accounts':0,
        'post_result_descriptive_arithmetic':{'C_2025_share_of_raw_net_event_return_sum':net_share,
            'scope':'Sum of separate event returns, not account performance or portfolio profit contribution.'}}
    save(WORK/'others/judgment.json',judgment)
    lines=['# EX020：五种入场表达竞争性诊断','',judgment['conclusion'],'',
        '本轮按用户“执行”完成1轮阶段二诊断。累计启动12轮、完成11轮、技术失败1轮，剩8轮。'
        '新增5种入场表达、0个完整策略配置、0次新完整账户；既有原型及历史证据保持。原五项策略目标未获新达标证据，不进入阶段三。','',
        '## 固定问题、样本和执行','',
        f"共{a['eligible']}个合格决策时点、{a['bootstrap']['sessions']}个计划入场交易日。"
        '仅使用原DFLS准备引用中的LITE30m四产品；2018-11至12预热，2019-01-02至2025-12-31开发。'
        '当柱完成后才可产生信号，下一段以信号收盘价加1%的固定限价尝试买入。持有N段，随后一段市价退出。'
        '单边0.1%，严格穿越触价、零滑点、单股数量，净价格收益=卖价×0.999/(买价×1.001)−1。'
        '没有2026价格补标签、退出优化或参数搜索。','',
        'A为收盘突破此前65柱最高价；B为上升SMA65背景中从均线下方回到上方；C为前柱收盘低于其SMA65至少2ATR13后，当前收盘越过前柱高点；'
        'AC为A加此前13柱平均TR不高于此前65柱的70%；AV为A加当前成交量至少为过去20个交易日同一美东时段中位数的1.5倍。'
        '这些是事前固定的工作表达，完整算法及等号见协议；不宣称代表整个理论或最优阈值。','',
        '[事前协议](protocols/design.md) · [授权](protocols/authorization.md) · [完整结构化分析](others/analysis.json)','',
        '## 事前主期限：自身收益与匹配增量','',
        '一般机会为同一合格总体；按同一年月份×计划入场美东时刻匹配，并按目标事件数加权。'
        '各信号所处背景不同，匹配均值也不同。对照包含目标自身；这是历史描述，不是可提前获知当月结果的交易规则。'
        '主期限不同，不能直接按表内平均收益给所有机制排名。','',
        '|表达|主N|完整标签|平均净价格收益|匹配一般机会均值|增量（百分点）|胜率|平均盈利/平均亏损|',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,n in PRIMARY.items():
        v=a['horizons'][str(n)]['signals'][name]
        p,m=v['raw']['price'],v['matched_raw']
        lines.append(f"|{name} {LABELS[name]}|{n}|{p['count']}|{pct(p.get('mean'))}|{pct(m['control_mean'])}|{100*m['difference']['mean']:.4f}|{pct(p.get('win_rate'))}|{number(p.get('payoff_ratio'))}|")
    lines+=['','## 减少重复覆盖同一段行情','',
        '按信号先后保留；下个信号必须严格晚于上个信号的固定持有及退出区间。选择不看未来成交或收益。'
        '这会改变抽样权重，不能把变化全部解释为重复信号的因果作用。独有入场日按计划入场日期计，不是信号完成日期。','',
        '|表达|主N|原始事件/独有入场日|去重事件/完整标签|去重净均值|去重匹配均值|增量（百分点）|去重胜率|盈亏比|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,n in PRIMARY.items():
        v=a['horizons'][str(n)]['signals'][name]
        p,m=v['nonoverlap']['price'],v['matched_nonoverlap']
        lines.append(f"|{name}|{n}|{v['raw']['events']}/{v['raw']['signal_days']}|{v['nonoverlap']['events']}/{p['count']}|{pct(p.get('mean'))}|{pct(m['control_mean'])}|{100*m['difference']['mean']:.4f}|{pct(p.get('win_rate'))}|{number(p.get('payoff_ratio'))}|")
    lines+=['','主期限采用共享20交易日连续块、1000次重抽样，每次重估同月×时刻控制均值。以下为边际描述性95%区间，'
        '未校正多重选择，也不消除开发池重复观察偏差；不设置新的显著性硬门。所有本次区间均有1000次有效抽样，0次空目标。','',
        '|表达|原始净均值区间（%）|原始增量区间（百分点）|去重净均值区间（%）|去重增量区间（百分点）|',
        '|---|---:|---:|---:|---:|']
    for name,n in PRIMARY.items():
        v=a['horizons'][str(n)]['signals'][name]
        x,y=v['bootstrap_raw'],v['bootstrap_nonoverlap']
        lines.append(f"|{name}|{interval(x['price_mean'])}|{interval(x['matched_difference'])}|{interval(y['price_mean'])}|{interval(y['matched_difference'])}|")
    lines+=['','C在主期限原始和去重样本的相对增量分别为+0.5786、+0.3050个百分点，方向一致。'
        '但去重自身净均值只有+0.0616%，区间跨零，胜率48.85%、盈亏比1.100。当前更适合称为值得追查的入场线索，不能称为已经证实的可交易优势。','',
        '## 附加条件是否改善基础突破','',
        'AC/AV与全部A事件按同月×计划入场时刻匹配。去重AC/AV仍以全部A作对照。'
        '表中“仅自身”表示控制格子只有该目标一个事件；“格子全为目标”包含多个目标但没有额外A事件的情形。'
        '后者整格平均差机械为零，不能解释为精确证明条件没作用。','',
        '|表达/样本|完整标签|相对A增量（百分点）|95%区间|控制数中位/最小|仅自身事件|格子全为目标事件|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name in ('AC','AV'):
        v=a['horizons']['65']['signals'][name]
        for mode,label in [('raw','原始'),('nonoverlap','去重')]:
            m=v['parent_matched_'+mode]
            s=m['control_support']
            lines.append(f"|{name}/{label}|{m['count']}|{100*m['difference']['mean']:.4f}|{interval(v['parent_bootstrap_'+mode]['matched_difference'])}|{s['median_control_events_per_target']:.0f}/{s['minimum_control_events']}|{s['singleton_target_events']} ({pct(s['singleton_target_events']/m['count'])})|{s['all_target_cell_events']} ({pct(s['all_target_cell_events']/m['count'])})|")
    lines+=['','AV原始相对A差为-0.0737个百分点，去重为+0.0735个百分点，两个区间均跨零；稀疏、自包含对照进一步限制判断，不能宣布放量有增量或无作用。'
        'AC主期限只有26个原始完整标签、17个去重完整标签，自身均值为负且低于普通机会，当前不支持优先投入。','',
        '一般机会对照的主期限格子中位均为21个事件，最小11至19个，全部表达均没有仅自身或全为目标的控制格子；详细支持量保存在analysis。','',
        '## 全部期限：保留不利及有利结果','',
        '|N|表达|原始完整数|原始净均值|匹配差（百分点）|去重完整数|去重净均值|去重匹配差（百分点）|',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for n in HORIZONS:
        for name,v in a['horizons'][str(n)]['signals'].items():
            p,q=v['raw']['price'],v['nonoverlap']['price']
            lines.append(f"|{n}|{name}|{p['count']}|{pct(p.get('mean'))}|{100*v['matched_raw']['difference']['mean']:.4f}|{q['count']}|{pct(q.get('mean'))}|{100*v['matched_nonoverlap']['difference']['mean']:.4f}|")
    lines+=['','C在26/65柱的原始与去重均值及匹配差均正，是辅助线索；130柱去重匹配差转负。'
        '不能事后把65柱选作主期限来回避13柱的薄弱绝对收益。A/AV在130柱自身均值更高却仍低于各自匹配机会；'
        '这不能归因于退出规则差，也不证明更长期趋势跟踪无效。AC在3柱去重结果有利，但样本少且不是主期限。','',
        '## 主期限年度、月份与集中性','',
        '|表达|计划入场年|完整标签|净均值|匹配增量（百分点）|','|---|---:|---:|---:|---:|']
    for name,n in PRIMARY.items():
        v=a['horizons'][str(n)]['signals'][name]
        for year,y in v['years'].items():
            p=y['raw']['price']
            delta=y['matched']['difference'].get('mean')
            lines.append(f"|{name}|{year}|{p['count']}|{pct(p.get('mean'))}|{'无样本' if delta is None else f'{100*delta:.4f}'}|")
    lines+=['','C原始主期限在7个年度的匹配差均正；2022年自身均值仍负。2025年均值约1.92%，明显强于其余多数年份。'
        f'事后按已保存年度均值×笔数核对，2025占全期单笔事件净收益合计{pct(net_share)}；'
        '它描述的是重叠事件的算术合计，不是账户盈利贡献。年份仅用作诊断，不设置事后年份开关或年度达标门。','',
        '|表达|有完整标签月份/84|净均值正月份|正收益合计最大单事件份额（原始/去重）|最大年度份额（原始/去重）|',
        '|---|---:|---:|---:|---:|']
    for name,n in PRIMARY.items():
        v=a['horizons'][str(n)]['signals'][name]
        months=[m['price'] for m in v['months'].values() if m['price']['count']]
        x,y=v['concentration_raw'],v['concentration_nonoverlap']
        lines.append(f"|{name}|{len(months)}/84|{sum(m['mean']>0 for m in months)}|{pct(x['largest_event_share'])}/{pct(y['largest_event_share'])}|{pct(x['largest_year_share'])}/{pct(y['largest_year_share'])}|")
    lines+=['','正收益总和只加正事件，不反映亏损抵消后的净收益稳定性。不能用C正收益份额看似分散来否认其净收益对2025的依赖。'
        '月度逐项描述保存在analysis；月份不是独立重复试验。','',
        '## 信息与持有路径：不等于可赚利润','',
        '|表达/主N|收盘信息均值|原始最低/最高收盘偏离均值|去重最低/最高收盘偏离均值|',
        '|---|---:|---:|---:|']
    for name,n in PRIMARY.items():
        v=a['horizons'][str(n)]['signals'][name]
        p,q=v['raw'],v['nonoverlap']
        lines.append(f"|{name}/{n}|{pct(p['information'].get('mean'))}|{pct(p['close_path_min'].get('mean'))}/{pct(p['close_path_max'].get('mean'))}|{pct(q['close_path_min'].get('mean'))}/{pct(q['close_path_max'].get('mean'))}|")
    lines+=['','信息收益为信号收盘至第N柱收盘，未扣执行延迟及费用。路径使用持有期完成柱Close相对买价的偏离并含初始0，'
        '不使用柱内高低先后，不能称为MFE/MAE、可兑现最高利润或账户最大回撤。路径已知但无法退出的事件仍保留路径，分母与收益不同，analysis分别给出。'
        '本轮未形成相近收益下风险改善的明确推荐依据。','',
        '## 无法评价的事件及样本分母','',
        '|表达/主N|原始状态|去重状态|','|---|---|---|']
    for name,n in PRIMARY.items():
        v=a['horizons'][str(n)]['signals'][name]
        lines.append(f"|{name}/{n}|{v['raw']['status']}|{v['nonoverlap']['status']}|")
    lines+=['','|N|一般机会状态|','|---:|---|']
    for n in HORIZONS:
        lines.append(f"|{n}|{a['horizons'][str(n)]['all']['status']}|")
    lines+=['','无入场、无退出、路径缺失和右截尾不补零、不延长区间，不读2026补齐。逐事件文件保留时点、限价、买卖价、状态及各表达成员。'
        '各期限的一般机会、信号与去重结果的胜率、盈亏比、分位数、路径分母、成交状态及重叠矩阵均完整保存在analysis。','',
        '## 技术验证与研究判断','',
        f"14项运行前聚焦合成检查及Ruff通过。运行内对EX019的3/13/26柱共{a['legacy_reproduction']['exact_event_rows']}条普通机会标签及PAT标志逐行精确复现。"
        f"结果核验覆盖{validation['event_rows']}条标签、{len(validation['cells_checked'])}个结果格，核对五条件、成本、分母、去重、一般机会及A对照、保存的抽样分位数。"
        '验证没有第二次独立计算所有历史特征或全部bootstrap权重；向量特征已与独立标量合成用例一致。技术通过不等于有效入场或策略达标。未做仓库全量回归。','',
        judgment['strongest_counterevidence'],'',judgment['interpretation'],'',judgment['next_step'],'',
        '下一步是本轮结果后提出的未执行建议。本轮没有新增验收门、触发完整账户、修改平台或访问封存行情。','',
        ' · '.join(['[聚焦检查](others/checks.json)','[结果核验](others/result_validation.json)',
        '[判断](others/judgment.json)','[逐事件标签](others/events.json.gz)','[信号事实](others/signal_facts.json.gz)',
        '[重抽样原值](others/bootstrap_draws.json.gz)','[运行前证据](others/pre_run_evidence.json)']), '']
    (WORK/'report.md').write_bytes('\n'.join(lines).encode('utf-8'))
    print('REPORT_RENDERED',flush=True)


if __name__=='__main__':
    main()
