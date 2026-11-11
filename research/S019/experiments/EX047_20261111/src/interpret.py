"""Bind the stage-three round-one interpretation to authenticated analysis."""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]
analysis = json.loads((WORK/'others/search_analysis.json').read_bytes())
execution = json.loads((WORK/'others/execution.json').read_bytes())
audit = json.loads((WORK/'others/semantic_audit.json').read_bytes())
assert analysis['status'] == execution['status'] == 'COMPLETE'
assert analysis['proposal_count'] == 144 and len(analysis['eligible_unique']) == 22
assert execution['workload']['candidate_runs'] == 144 and execution['workload']['benchmark_runs'] == 1
assert len(audit['results']) == 8 and sum(r['decisions'] for r in audit['results']) == 125616
value = {
    'title':'新授权阶段三第1轮：连续退出三族联合扩域',
    'conclusion':'本轮144次提议及144个策略账户、1个共享买持全部完成，22个配置通过原中心六门。硬退出与可恢复渐进族获得更高NAR的完整配置；单向渐进族的原C0801控制仍领先。最高新增达标点C0924为NAR70.3681%、MDD13.9984%、Calmar5.026881。下一轮检验这些收益改进在参数联合变化下是否保持。',
    'findings':[
        '使用Optuna4.9.0约束多变量TPE，三族各48次新提议、每族4点固定反馈、12进程各1原生线程；硬/单向/可恢复族分别导入5/8/8份同源码同执行输入历史观察，已全部复核完整指标。InMemoryStorage与JSON导入/ask/result/tell/检查点留证。各族新提议投入相同，5/6/6维覆盖难度及既有观察数量差异分别披露；族间最佳成绩按完整配置比较。',
        '硬退出C0829较C0720的精确控制C0807，NAR提高1.6913个百分点，MDD增加0.8575个百分点，Calmar降低0.230433。其q=0.254069、t=0.931216、h=0.447865越过EX045旧域；在本轮扩大后的域内均未贴边。117个共同闭合入场及退出全部相同，改进主要体现仓位和资金路径。旧域外42次提议中5个达标，旧域内6次中2个达标，计数含原控制，有限自适应样本不作无条件概率估计。',
        '单向渐进48次提议有9个达标；最高NAR仍为C0801精确复算C0855（64.7443%、MDD12.3975%、Calmar5.222378）。新增配置的最高NAR为C0899的64.0385%，Calmar5.064655。扩域为该族增加了较低收益达标点，尚无高于原控制的达标NAR。',
        '可恢复渐进C0924较C0804精确控制C0903，NAR提高4.0633个百分点，MDD增加1.3843个百分点，Calmar降低0.229536。六个参数均在EX045渐进族旧连续域内；这是原表达下的联合配置增益，域扩展的单独贡献尚无配对依据。退出宽度0.715848ATR、阈值2.287110ATR，弱势仓位0.432124、低参与乘数0.496987；同时变化的参数共同解释收益与风险取舍。116个共同闭合入场中114个退出相同，2个退出不同。',
        '三个最高NAR代表均未接近新域边界（以域宽5%诊断）。C0925的退出宽度0.111015接近0.1下界，NAR66.2772%、Calmar5.371895；保留其较高Calmar、窄区间的线索。本轮已有硬退出族对照，下一轮先检查领先宽度与原控制的局部交互，暂未在C0925附近进一步缩小宽度。',
        'C0924相对C0804的年度log增长增量在2022、2023为负，在2024、2025、2026为正，主要正增量来自2025和2026。2026-05-19共同入场周期的损益/入场权益改善3.5597个百分点；2022-06-09和2026-07-02周期分别恶化1.4968和1.2648个百分点。该归一化账本比较保留各自资金与复利路径。其MDD从2026-10-07延续至样本末2026-10-30，期末仍未恢复并保留一个持仓周期。',
        'scikit-learn RandomForest五折留出拟合及参数置换重要性帮助定位线索：硬退出的ATR距离、单向渐进的参与阈值、恢复族的低参与仓位值得在账户层面继续检查。Calmar的OOF R²分别约0.559/0.287/0.316，MAE约0.380/0.347/0.374；后两族拟合误差明显高于部分前沿的Calmar余量，因此下一轮用明确因素对照检验交互。模型只解释本轮自适应参数样本，不参与硬门与正式NAR排序。',
        '三份原型控制的逐柱、逐日、目标与成交精确一致；所有144账户完成身份、时序、现金、整数成交核对。8个代表账户共125616条决定完成独立业务重建，全部通过。完整参数、年度与交易损益、正反例、域内外及模型拟合证据见[联合搜索分析](others/search_analysis.md)和[结构化分析](others/search_analysis.json)。'
    ],
    'next_action':'继续新10轮额度内的阶段三。对各族原六门后最高NAR点和原控制采用相同局部诊断：有效轴上下5%、退出二轴角点、参与三轴角点及全轴同向变化；原型与赢家相同时只保留一个锚点。该开发性设计先识别敏感方向，完整邻域80%与费用压力验收保持待后续阶段批准。'
}
target = WORK/'others/interpretation.json'
assert not target.exists()
target.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
print('INTERPRETATION_READY')
