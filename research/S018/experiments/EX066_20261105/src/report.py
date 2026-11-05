"""Render the research interpretation from the published compact observations."""
from pathlib import Path
import json
from collections import Counter

WORK=Path(__file__).resolve().parents[1]
OUT=WORK/'others'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def metrics(f): return {x['metric']:x['value'] for x in f['diagnostics']}
rows=read(OUT/'window_results.json')
summary=read(OUT/'summary.json')
receipt=read(OUT/'computation_receipt.json')
names={'center-net-calmar':'净卡玛门','center-absolute-dd':'绝对回撤门',
       'center-relative-dd':'相对回撤门','frequency-median':'频率中位数','frequency-coverage':'频率覆盖率'}

def table(group):
    lines=['|窗口|选择期|观察期|前段可选数|选中配置|后段卡玛／买持|后段原集合名次|未保持条件|',
           '|---|---|---|---:|---|---|---|---|']
    for r in rows:
        p=r['pair']
        if not p['pair_id'].startswith(group):
            continue
        a,b=p['selection'],p['observation']
        obs=r['observations']
        selected='、'.join(x.removeprefix('S018-') for x in r['selected']) or '无人达标'
        ds='；'.join(dict.fromkeys(f"{o['primary_value']:.3f}／{o['benchmark_primary_value']:.3f}" for o in obs)) or '不适用'
        ranks='；'.join(dict.fromkeys(f"{o['rank_min']}–{o['rank_max']}/{o['reference_size']}" for o in obs)) or '不适用'
        failures='、'.join(dict.fromkeys(names.get(c['target']['target_id'],c['target']['target_id'])
            for o in obs for c in o['checks'] if c['status']=='FAILED')) or '不适用'
        lines.append(f"|{p['pair_id']}|{a['start_session']}～{a['end_session']}|{b['start_session']}～{b['end_session']}|{r['eligible_count']}|{selected}|{ds}|{ranks}|{failures}|")
    return '\n'.join(lines)

center=[]
for r in rows:
    if not r['pair']['pair_id'].startswith('MAIN'):
        continue
    v,b=metrics(r['center_observation']),metrics(r['benchmark_observation'])
    coverage=r['center_observation']['frequency_coverage']
    gates={'center-net-calmar':v['NET_CALMAR']>=1.5*b['NET_CALMAR'],
           'center-absolute-dd':v['DRAWDOWN_MAGNITUDE']<=.25,
           'center-relative-dd':v['DRAWDOWN_MAGNITUDE']<=.8*b['DRAWDOWN_MAGNITUDE'],
           'frequency-median':v['FREQUENCY_MEDIAN']>=6,
           'frequency-coverage':coverage['covered_windows']*10>=coverage['total_windows']*9}
    center.append({'pair_id':r['pair']['pair_id'],'observation':r['pair']['observation'],
                   'metrics':v,'benchmark':b,'original_condition_readout':gates,
                   'all_conditions':all(gates.values())})
assert len(center)==8 and sum(x['all_conditions'] for x in center)==4
assert all(c['metrics']['NET_ANNUAL_RETURN']>0 for c in center)
failure_counts=Counter(c['target']['target_id'] for r in rows for o in r['observations']
                      for c in o['checks'] if c['status']=='FAILED')
interpretation={'note':'RSCH readout of original five inequalities on existing window facts; not a new acceptance policy.',
                'center_main_observations':center,'winner_failure_counts':dict(failure_counts),
                'all_windows_information_complete':summary['status']=='COMPLETE'}
(OUT/'interpretation.json').write_text(json.dumps(interpretation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
center_lines=['|观察窗|C9380净年化|局部回撤|净卡玛|买持净卡玛|60日中位数|≥3笔覆盖率|原五条件对照|',
              '|---|---:|---:|---:|---:|---:|---:|---|']
for c in center:
    v=c['metrics']
    b=c['benchmark']
    failed='、'.join(names[k] for k,ok in c['original_condition_readout'].items() if not ok) or '全部满足'
    center_lines.append(f"|{c['pair_id']}|{v['NET_ANNUAL_RETURN']:.2%}|{v['DRAWDOWN_MAGNITUDE']:.2%}|{v['NET_CALMAR']:.3f}|{b['NET_CALMAR']:.3f}|{v['FREQUENCY_MEDIAN']:.0f}|{v['FREQUENCY_COVERAGE']:.0%}|{failed}|")

report=f'''# EX066：C9380选型稳定性补查完成，历史择优优势缺乏持续性

本轮按2026-11-05用户授权完成第六项选型稳定性补查。新增策略回放、搜索点、候选登记及前五项重算均为0；保留C9380参数、原目标和历史资格。计算完整，选择稳定性证据偏弱，不能把本项写为“稳健性通过”。不自动进入阶段五。

## 做了什么

复用阶段三全部741个不同完整配置的正式MU日线账户，含248个全期失败者；762次原始评价的定义去重和别名映射保持。实际窗口选择不读取全期通过标签。按原五个经济／频率硬条件筛选，再按原始净卡玛择优，全部并列保留，没有引入阶段四参数、压力或分箱排序。

主设计为252交易日选择＋紧接252日观察、步长63日，共8对；较长选择期对照为504＋252日，共4对。合计16个唯一窗口、11,888份账户窗口事实，完整固定日历为961日。设计与预算在计算前固定，详见[设计](protocols/design.md)、[强类型请求](protocols/request.json)、[选择规则](protocols/rule.json)及[来源映射](protocols/source_manifest.json)。

本项模拟阶段三按原D推荐的回顾性稳定性，不复现用户人工批准C9380，也不模拟每个历史窗口重新研究策略。全部配置来自已见完整开发池，前后切窗不会恢复独立性。

## 得到了什么

|结果|252＋252主设计|504＋252较长选择期|
|---|---:|---:|
|计划窗口对|8|4|
|前段无人达标|3|0|
|能够选出赢家的窗口|5|4|
|后段选中成员观察数|5|7|
|后段保持全部原条件|0/5|0/7|
|后段明确失败／未知|5／0|7／0|
|后段卡玛高于同窗买持|2/5|1/7|
|C9380前段符合原条件|4/8|3/4|
|C9380进入最优并列集合|0/8|0/4|

7个较长选择期观察来自4个窗口，其中一个窗口有4个并列定义；这些成员不独立。两套设计的部分观察期重复，不合并为12次独立成功或失败，也不由0/5、0/7推导未来成功概率。

主设计前3窗全族无人达标。后5窗的优胜配置全部在后段至少违反一个原条件：5/5均因交易频率中位数不足，4/5还未达到买持1.5倍净卡玛，其中1个早期赢家另突破25%回撤门。较长选择期没有改善条件保持，7/7同时未保持频率中位数和相对净卡玛门。后段卡玛本身仍为正，不能把“未保持原条件”写成“全部亏损”。

主设计后5个赢家的后段净卡玛为3.293～14.724、中位6.630；相对买持卡玛差中位-1.527。其在原前段可选集合中的后段名次依次为6/20、515/641、585/661、391/662和383/569。后4窗均落到原参照集合的后半部，显示前段最优身份和相对优势没有稳定延续。

### C9380自身与选型过程要分开解释

C9380在两套设计中都未成为前段净卡玛最优者；这削弱“全期最高D可稳定定位优胜参数”的解释，但不意味着C9380自身经济表现很差。主设计8个后段中，C9380净年化均为正，局部回撤7.34%～8.57%，8/8保持相对和绝对回撤门及冷区频率覆盖率。按原五条件直接对照，前4个后段全部满足，后4段频率中位数均为5笔而非要求的6笔；其中后3段还不满足买持1.5倍净卡玛。

因此，较低回撤表现具有一定跨段延续性，而交易频率和相对卡玛优势并未在所有时期保持。全期95笔交易、中位6及覆盖100%的原结论不变；局部后段中位5反映交易机会随时期变化，不能用全期中位数掩盖，也不新增“每个年度必须达标”的否决条件。

## 研究判断与下一步建议

本项没有提供“C9380可由较早窗口稳定选中且后来保持原条件”的支持。延长选择期也没有解决选择结果保持问题。原阶段四适用数值硬门通过与本项显示的选型不稳定可以同时成立；不把任何一项替代另一项，也不改变原验收资格。

建议保持C9380定义，停止通过同一开发池微调来追求更好自检读数；把它保留为有明确历史低回撤表现、但选型稳定性不足的候选。若用户仍选择推进阶段五，应明确接受这些经济证据局限：技术检验只验证行为等价和隔离业务链可运行，不会证明经济稳定性。没有自动进入阶段五、冻结、部署或前瞻交易。

## 适用范围和保留风险

- 最后观察窗均止于2026-10-08，开发池至2026-10-30的剩余16个交易日未进入完整观察窗；不能声称本项覆盖完整十月下跌尾段。按事前完整窗口规则不临时追加尾窗。
- 原净卡玛相对门没有买持负值时的正收益分支。负买持窗口的门槛含义已保留，没有事后改门；本次全部选中成员后段卡玛均为正。
- 窗口账户继承资金和持仓，回撤从前收盘基点计局部高点；不是重新投入本金的独立回测，不能拼接成动态择优交易业绩。
- 配置形成过程已使用全开发池；窗口重叠、参数及并列成员高度相关。本项不估计DSR试验数、不替代PBO／DSR、不证明已排除选择偏差。
- 本轮只为C9380阶段四新增诊断。其他492个已登记达标候选并未因此完成阶段四；741项是模拟原选型竞争范围。

## 附录A：逐窗选择与后段观察

### 主设计

{table('MAIN')}

### 较长选择期对照

{table('LONG')}

后段排名以该窗前段可选集合为固定参照，不按后段是否达标再过滤；名次区间保留并列，不把多个并列成员平均成组合。

## 附录B：C9380固定身份后段表现

{chr(10).join(center_lines)}

表中窗口日期与附录A主设计一致。这是对既有窗口事实按原五个不等式的RSCH解释性对照，不更改平台结果或新增政策；详见[逐项解读](others/interpretation.json)。

## 附录C：复用、计算和发布证据

实际读取3,616,686,764字节、1,510次物理文件读取，解码1,485份唯一文档：741来源头部、741策略账户、1共享输入和2买持账户。不同实验路径的同内容共享来源仍逐路径读取哈希，但只解码一次。实际投影743账户×16窗口，共11,888事实，观察点714,023、窗口点访问3,744,720、频率子窗3,043,328。

主计算及首次独立附证发布共{receipt['total_seconds']:.2f}秒：TDR读取投影{receipt['projection_wall_seconds']:.2f}秒、选型{receipt['selection_seconds']:.2f}秒、证据序列化{receipt['serialization_seconds']:.2f}秒、独立材料发布{receipt['publication_seconds']:.2f}秒。TDR内读取{receipt['projection_stats']['read_seconds']:.2f}秒、JSON解码{receipt['projection_stats']['decode_seconds']:.2f}秒、投影{receipt['projection_stats']['projection_seconds']:.2f}秒；其余为来源关联、共享身份和组织成本。前置来源盘点及后续阶段交付发布不包含在上述102.58秒内。没有把差额时间当作策略回放。

[运行回执](others/computation_receipt.json)绑定独立证据`{receipt['evidence']['sha256']}`；该材料包含完整输入、规则、事实与分析结果。[逐窗输出](others/window_results.json)及[汇总](others/summary.json)供直接查阅。研究源码、协议和报告入Git；约73.13MB独立证据及原始账户在assets中保留，Git不能替代本地资产备份。独立材料中的源引用不意味着把全部原账复制进新交付。

ASSESSMENT/2仅追加本项材料与研究报告；原ASSESSMENT/1的结构化payload（包括前五项请求、面板、比较、历史推荐文字）逐字段完整保留，其历史推荐须结合本次新增报告理解。保护文件与原payload哈希核对见[保留检查](others/preservation_check.json)，正式引用及验证见[发布回执](others/publication_receipt.json)。INTEGRITY只核对字节与声明引用，不重算本项或前五项，也不作独立经济认证。

本轮选型稳定性补查工作已完成；结论为证据偏弱，不声称稳定性通过。下一步请用户决定是否接受上述局限并选择C9380进入阶段五技术检验。
'''
(WORK/'report.md').write_text(report,encoding='utf-8')
print('REPORT_READY',dict(failure_counts))
