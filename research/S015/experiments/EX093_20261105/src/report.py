"""Summarize the declared diagnostic without treating COMPLETE as acceptance."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]
OUT=HOME/'others'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def pct(x):return '不可用' if x is None else f'{100*x:.4f}%'

def main():
    result=read(OUT/'selection_result.json');projection=read(OUT/'projection.json')
    rows=read(OUT/'results.json')['accounts']; mapping={f"S015-{r['proposed_candidate_id']}":r['old_candidate_id'] for r in rows}
    sources={x['candidate']['candidate_id']:x for x in projection['sources']}
    facts={(x['source_id'],x['window']['window_id']):x for x in projection['facts']}
    def metric(f,name):return next(x['value'] for x in f['diagnostics'] if x['metric']==name)
    table=[]
    for decision in result['decisions']:
        obs=[x for x in result['observations'] if x['pair_id']==decision['pair_id']]
        for x in obs:
            cid=x['candidate']['candidate_id']
            observed=facts[(sources[cid]['source_id'],x['observation_window_id'])]
            prior=facts[(sources[cid]['source_id'],decision['selection_window_id'])]
            table.append(f"|{x['pair_id']}|{len(decision['eligible'])}|{cid}（原{mapping[cid]}）|{pct(metric(prior,'NET_ANNUAL_RETURN'))}|{pct(observed['period_return'])}|{pct(x['primary_value'])}|{pct(x['excess_primary'])}|{x['rank_min']}–{x['rank_max']}/{x['reference_size']}|{x['acceptance_status']}|")
        if not obs:table.append(f"|{decision['pair_id']}|{len(decision['eligible'])}|{decision['status']}|—|—|—|—|—|—|")
    center='S015-C9820';src=sources[center];centertable=[]
    for pair in projection['request']['plan']['pairs']:
        f=facts[(src['source_id'],pair['observation']['window_id'])]
        b=facts[(src['benchmark_source_id'],pair['observation']['window_id'])]
        annual=metric(f,'NET_ANNUAL_RETURN');bh=metric(b,'NET_ANNUAL_RETURN')
        dc=next(x for x in result['decisions'] if x['pair_id']==pair['pair_id'])
        chk=next(x for x in dc['checks'] if x['candidate']['candidate_id']==center)
        selected=any(x['candidate_id']==center for x in dc['selected'])
        rank='不适用（前段未合格）'
        if any(x['candidate_id']==center for x in dc['eligible']):
            score=(-annual,metric(f,'DRAWDOWN_MAGNITUDE'))
            peers=[]
            for peer in dc['eligible']:
                pf=facts[(sources[peer['candidate_id']]['source_id'],pair['observation']['window_id'])]
                peers.append((-metric(pf,'NET_ANNUAL_RETURN'),metric(pf,'DRAWDOWN_MAGNITUDE')))
            rank=f'{1+sum(x<score for x in peers)}–{sum(x<=score for x in peers)}/{len(peers)}'
        centertable.append(f"|{pair['pair_id']}|{chk['status']}|{'是' if selected else '否'}|{pct(f['period_return'])}|{pct(annual)}|{pct(annual-bh)}|{pct(metric(f,'DRAWDOWN_MAGNITUDE'))}|{rank}|")
    center_summary=next(x for x in result['candidates'] if x['candidate']['candidate_id']==center)
    text=f'''# EX093 V4原生参数族选型稳定性

完成完整164配置的固定集合回顾性诊断，计算状态为 **{result['status']}**；这表示事实计算完整性，不是经济稳定性PASS，也不改变原候选资格。C9820对应原C9304，在{center_summary['planned_windows']}个计划窗口中被选中{center_summary['selected_windows']}次，可决定窗口{center_summary['decided_windows']}个。

## 范围和预先声明规则

完整保留EX076的8个、EX077的124个、EX078的32个配置，共164个不同参数内容；原生V4内容仍164个唯一身份。原历史156组双窗权益路径不等于156个参数配置，本轮不按绩效、轨迹相同或原资格删样。该集合是在机制固定后的阶段三参数族，不是历史606个跨机制配置，更不是全部研究选择历史。

标准费用0.1%，full434日连续账户，后复权信号、未复权交易。执行遵循EX092的V4原生语义：空仓按目标比例入场，已持仓不补买，未成交期间按当日条件重试；allocation解释为入场参考价股票市值比例。该执行语义不同于原含费周期现金预算，不继承旧族经济结论。

先按原STANDARD净年化、回撤及60日频率硬条件筛选，再按净年化降序、相同值按回撤升序，完全并列全部保留。此为新声明的诊断排序，不声称复现原双窗口Pareto与人工最终选择，也不改前五项自检。S011独立共同窗比较继续由中心账户检查承担，不将其不同窗口收益常数混入本项。

三个252日选择+60日观察窗口按尾端对齐；观察依次为2026-01-20至04-22、04-23至07-21、07-22至10-21。选择窗重叠，观察窗连续；窗口沿用原账户权益与持仓，不独立空仓重放。每个60日观察仅有一个完整滚动频率子窗。参数原先使用整个开发样本形成，因此本项不是无选择泄漏的历史模拟部署，也不是独立验证。

## 前段选择与后段表现

60日年化指标仅用于统一尺度，短窗值可能被显著放大；同时报告实际60日累计净收益，不作为全年预测。

|窗口|前段合格数|选中配置|前段净年化|后段累计净收益|后段净年化|后段年化超额|在前段合格集合中的后段名次|后段目标|
|---|---:|---|---:|---:|---:|---:|---|---|
{chr(10).join(table)}

没有合格候选的窗口数为{result['no_eligible_windows']}；选择证据不足{result['insufficient_selection_windows']}；观察不足{result['observation_incomplete_windows']}；排名不足{result['ranking_incomplete_windows']}。后段目标通过{result['passed_observations']}、失败{result['failed_observations']}、未定{result['indeterminate_observations']}个已选观察。后段排名始终使用前段锁定的合格集合，不按后段表现重新筛人。

P1、P2均为164/164配置未达到“净年化至少为同窗买持的1.5倍”，不是来源不足。中心C9820前段净年化分别77.1366%、89.9701%，对应门槛108.8620%、147.6404%；其他回撤及频率条件没有补偿收益门槛。P3选中C9877的后段失败项仅为60日闭合交易中位数3笔，低于原门槛6笔；其收益、回撤及覆盖率条件通过。完整逐项失败事实见[门槛解释](others/failure_explanation.json)。

本次结果支持“固定参数族的合格性和净年化优先选型随时间变化”，不支持把前段赢家视为后段持续领先者。该诊断采用新声明排序，与历史双窗Pareto及人工权衡不同，不将其结果回写为原五项自检失败，也不撤销历史S015资格。

## 固定中心C9820的后段观察

以下仅用于解释当前中心，不以事后表现替换前段选中者。中心名次由RSCH使用公开投影事实按相同净年化降序/回撤升序计算，范围固定为前段合格集合；前段未合格时不赋名次。

|窗口|中心前段硬门|入选|中心后段累计净收益|中心后段净年化|中心后段年化超额|中心后段回撤|后段名次|
|---|---|---|---:|---:|---:|---:|---|
{chr(10).join(centertable)}

## 计算与证据

复用EX092中心标准账户，新增163个成功策略账户。一次编号冲突在对应配置计算前发现：拟C9950已被旧候选占用，改用C9826；保留原C9112的参数和来源映射，不涉及结果选择。首次完成36个新增账户后受控停止并保存引用，其余127个续跑。恢复重新计算一次共用买持，累计2次买持计算，内容身份一致，正式投影仍只含1个唯一买持。另有沙箱首次worker启动拒绝（0计算）及受控中断的一批最多12个未发布任务；额外CPU开销无法由成功账户计时精确还原，不计为零。

正式投影共{len(projection['facts'])}个窗口事实，读取字节{projection['stats']['source_bytes']}，共享字节{projection['stats']['shared_bytes']}，耗时{projection['stats']['total_seconds']:.3f}秒；窗口分析没有重放账户。逐窗口事实、所有失败条件和分母完整保留。

[原配置映射](protocols/universe.json)、[原生内容映射](others/content_mapping.json)、[规则](protocols/rule.json)、[窗口计划](protocols/plan.json)、[编号修正与恢复记录](protocols/id_correction.json)、[账户引用](others/results.json)、[投影事实](others/projection.json)、[完整选型结果](others/selection_result.json)、[独立自检证据](others/selection_stability.json)。

下一步：结合EX092原五项自检与本项限制报告升级后的完整研究结论；不凭COMPLETE或单个优胜窗口批准冻结、部署或生产操作。
'''
    (HOME/'report.md').write_text(text,encoding='utf-8')
    print('REPORT_READY',center_summary)

if __name__=='__main__':main()
