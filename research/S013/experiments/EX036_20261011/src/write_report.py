"""Reproduce the complete diagnostic report from exact retained outputs and decision."""
from common import ROOT,SRC,read


def main():
    base=ROOT/'.tmp/ex036-diagnosis'
    confirmation=read(base/'confirmation_v2.json')
    drawdown=read(base/'drawdown_v2.json')
    decision=read(SRC.parent/'protocols/decision.json')
    assert confirmation['status']==drawdown['status']=='PASS'
    assert confirmation['new_account_evaluations']==drawdown['new_account_evaluations']==0
    text='''# S013：确认边界与年度回撤完整路径诊断

身份RSCH，S013阶段三。用户授权自主推进目标，无需逐轮评审。本轮只精确复用34个独立已有原生账户，零新增策略评价、零新增业务配置、零候选登记；原33账户与均值居中C8701均属反复使用的开发池。本轮完成不等于改善目标达成。

## 方法与技术修订

执行前正式声明两项方法及源码哈希，保留原C2132和32个原完整13维联合扰动点、全部自然年与原生机会。逐账户完整正式序列化、候选内容/源码/依赖/参数、运行绑定、评价身份、参数派生关系及现金/数量/费用账本核对。确认分由原绑定HFQ数据独立重算自相关、量额、因果归一秩和原权重，并核对原入场/退出全状态。

初次确认检查将EvaluationIdentity与CandidateContentIdentity整对象比较而失败；共同content哈希一致。独立v2方法按各自公共字段语义核验，保留原评价的输入/协议/环境哈希，另核对内容/源码/依赖及绑定/派生。初次回撤输出在严格JSON序列化失败：2388个非有限输出位置全部为没有实际交易周期的actual_cycle_id，经济数值没有非有限值。独立v2仅将原记录中缺失周期编号以object dtype保留为null；所有其他非有限值继续拒绝。原源码、方法、失败、精确空值路径和修订方法均保留；不改变账户、年份、点集、权重、计算或经济要求。

## 原生确认机会与固定权重替代

以下是原生信号机会和当日判断，不是实际完成交易数或新策略收益。机会集合依各自既有持仓路径变化。统计按信号日期分年，首个2020执行可能对应2019信号；实际经济年仍按连续账户执行日期。三个预先固定权重：原权重(自相关0.5、成交额0.25、成交量0.25)，三个分量等权，剔除自相关后量额各0.5。替代判断保持各自原阈值，不传播持仓、订单、资金或收益。

|账户组|路线|原机会|原通过|原拒绝|等权通过|量额通过|
|---|---|---:|---:|---:|---:|---:|
'''
    summary=confirmation['summary']
    for label,rows in (('原中心',summary['center_statistics']),('33账户合并描述',summary['pooled_native_opportunity_statistics'])):
        for row in rows:
            if row['year']!='ALL':
                continue
            weights=row['fixed_weight_predicate_diagnostics']
            text+=f"|{label}|{row['route']}|{row['native_opportunities']}|{row['passes']}|{row['rejections']}|{weights['score_equal_features']['alternative_pass_count']}|{weights['score_without_acf']['alternative_pass_count']}|\n"
    totals=summary['paired_same_flat_totals']
    text+=f"\n32对已有路径的相同空仓策略状态中，共{totals['same_prestate_flat_days']}个配对日；原基础资格不同{totals['eligibility_disagreement_days']}日，确认通过不同{totals['native_score_pass_disagreement_days']}日，实际当日入场目标不同{totals['native_entry_target_disagreement_days']}日。双方都符合基础资格时，确认通过不同{totals['both_eligible_score_disagreement_days']}日。重复配对日并非独立样本；共同空仓状态不等于共同继承现金。四种跨特征/阈值判断及所有分量距离分布保存在正式数据中，不解释为单个参数因果作用。\n\n"
    text+='## 全年度回撤与实际路线\n\n年度开头继承连续账户权益，峰谷按实际净值确定。路线分组的每日对数收益相加严格等于该峰谷净值比的对数，误差低于1e-12。下表分组值是已发生路径的描述，不能解释为删除该路线后可获得的利润，也不是各路线独立最大回撤。信号模型的活动路线和实际成交库存分别保留。\n\n|中心|年|年度回撤|基准回撤|年度回撤门|峰谷区间bull对数收益|bear对数收益|flat对数收益|\n|---|---:|---:|---:|---|---:|---:|---:|\n'
    for label,row in drawdown['rows'].items():
        for year in row['annual_drawdowns']:
            groups={g['execution_route']:g['sum_daily_log_return'] for g in year['by_executed_route']}
            text+=f"|{row['candidate_id']}|{year['year']}|{year['drawdown']:.4%}|{year['benchmark_drawdown']:.4%}|{'通过' if year['annual_drawdown_gate_pass'] else '未通过'}|{groups.get('bull',0):+.4%}|{groups.get('bear',0):+.4%}|{groups.get('flat',0):+.4%}|\n"
    text+='\n全窗每个模型持仓信号日的入场锚点逆向价格位移、严格过去20日平均真实波幅单位及两次连续不高于锚点的标记全部保留。锚点是HFQ信号入场Close，实际成交价及费用独立；此处没有新增止损规则，也没有回放替代账户。\n\n## 研究判断与下一步\n\n'
    text+='\n\n'.join(decision['conclusions'])+'\n\n'
    text+=decision['next_action']+'\n\n'
    text+='原四项经济要求和全部13数值域保持；描述统计、替代判断及路线分解均不新增经济否决门。所有已见年份和原32点保留。技术FULL仅核验声明证据完整性；没有独立样本、未来收益保证或实质参数改善证明。总目标仍未达成。未推进正式阶段四交接、冻结、PTE或生产。\n'
    report=SRC.parent/'others/report.md'
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(text,encoding='utf-8',newline='\n')
    print({'report':'COMPLETE','objective_achieved':False},flush=True)


if __name__=='__main__':
    main()
