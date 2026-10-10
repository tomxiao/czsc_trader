"""Report short bear ACF aggregation against all prospective controls."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    diagnosis=read(RUNS/'previous_path_diagnosis.json')
    text='''# S013：下跌自相关严格过去基准居中对照

RSCH阶段三，用户授权自主完成目标，无需逐轮评审。COMPLETE指本轮证据交付，参数敏感性目标另判。

## 已有证据、机制和最强反证

C2132中心年化16.1572%、全窗回撤14.1599%，原四门通过；同13维原共同域的32点收益Q10仅5.8974%、回撤Q90达30.5044%，收益退化10.2598、回撤恶化16.3446个百分点。EX012原买入确认没有直接拒绝三个背景的bear机会，关闭确认后过滤门槛和期限脆弱性仍在。EX013五个删项新中心均未达标。EX015的20日均值与EX027的3日中位数/均值中心均未达标，简单平滑当前信号不能视为改进。价格保护与路线平滑等负面结果一并保留。

原32账户的逐日路径诊断仅描述已观察现象：核对完整不可变账户、请求和参数绑定，识别首次仓位分歧来自入场还是退出，记录全年及2023仓位不同天数、原始门槛变化天数。联合扰动同时改变多维，不能把描述关联当单个参数因果贡献。新中心规则不按某笔交易利润修补。

本轮保留当前原ACF20，减去严格过去L个完整ACF估计的基准，N0为中位数、N1为均值，再与原bear.acf_min比较。ACF20衡量相邻涨跌是否延续；居中询问当前延续程度是否高于近期通常水平，并不平均掉当前信号。基准shift1，不含当前、无填补。L沿用原confirmation.lookback，不新增窗口搜索；这个数值参数同时影响原确认和新基准，新增耦合明确披露。门槛现在是当前减基准的相关系数差值，与原绝对值门语义有变；同坐标实验比较机制，不声称两门经济含义完全相同。

原bullACF/确认分/快速raw路线/区间/期限/所有退出/二元仓位及执行保持。新基准需L+21价格，热身max(parent,L+21)，中心仍180；参数域部分点可多1日，仅用既有S013绑定资产，缺失必须明确失败，不下载或兜底。原13数值坐标和完整域仍活跃，不增加或删掉坐标。

原TIME、EX027短中位数和短均值3个完整中心精确复用，2个新中心共5格。任一新中心达标则原TIME32点精确复用、N0/N1均完整32新点；未达标者仅事前对称诊断，不登记。全部13数值中心和点坐标相同；无新达标则无新参数评价。

最强反证：基准可能适应真实有效信号，放入不良交易，并增加确认lookback与bear门交互；H整数和路线阈值仍可能脆弱。更强中心、较弱中心机械缩小退化、有限参数点均不能单独证明稳定。已见EX012..27开发证据后设计，反复搜索偏差存在，没有独立验证，也未新选基准长度/阈值。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp、策略与可执行LimitBuyHold都1%买入溢价。仅用授权S013已有数据。原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤与参数诊断不新增经济门。

## 五个完整中心账户

|机制|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        r=a['rows'][cell['label']]
        failed='、'.join(k for k,v in r['gates'].items() if not v)
        text+=f"|{cell['mechanism']}|{r['candidate_id']}|{r['net_cagr']:.4%}|{r['drawdown']:.4%}|{r['closed_trades']}|{r['annual']['2022']['return']:.4%}|{r['annual']['2023']['return']:.4%}|{'通过' if r['qualified'] else failed}|\n"
    text+='\n## 完整参数诊断\n\n'
    business=actual=reused=0
    relative=[]
    substantive=[]
    if p['status']=='PASS':
        manifest=read(PROTOCOLS/'parameter_plans.json')
        business=manifest['new_parameter_business_accounts']
        actual=p['actual_parameter_evaluations']
        reused=manifest['reused_parameter_accounts']
        text+='全部13原共同域、总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数，无缩域/删点/换点。\n\n'
        text+='|中心|收益Q10|回撤Q90|收益退化pp|回撤恶化pp|邻点四门通过|\n|---|---:|---:|---:|---:|---:|\n'
        for label,r in p['summaries'].items():
            text+=f"|{label}/{r['candidate_id']}|{r['q10_cagr']:.4%}|{r['q90_drawdown']:.4%}|{r['return_degradation']*100:.4f}|{r['drawdown_degradation']*100:.4f}|{r['qualified_points']}/32|\n"
        for label,d in p['differences_from_original'].items():
            text+=f"\n{label}相对原规则：收益Q10{d['q10_cagr_difference']*100:+.6f}、回撤Q90{d['q90_drawdown_difference']*100:+.6f}、收益退化{d['return_degradation_difference']*100:+.6f}、回撤恶化{d['drawdown_degradation_difference']*100:+.6f}个百分点。\n"
            if label in qualified and d['return_degradation_difference']<0 and d['drawdown_degradation_difference']<0:
                relative.append(label)
                if d['q10_cagr_difference']>0 and d['q90_drawdown_difference']<0:
                    substantive.append(label)
        pairs=read(RUNS/'parameter_pairs.json')
        assert pairs['status']=='PASS'
        for label,r in pairs['comparisons'].items():
            text+=f"\n{label}同坐标{r['complete_pairs']}对：年化更好{r['cagr_better_points']}、更差{r['cagr_worse_points']}；回撤更小{r['drawdown_better_points']}、更大{r['drawdown_worse_points']}；平均年化差{r['mean_cagr_difference']*100:+.6f}、回撤差{r['mean_drawdown_difference']*100:+.6f}个百分点。\n"
        text+='\n未达标中心只诊断；相对退化与绝对尾部一起解释。32有限点不是置信区间或独立验证。\n'
    else:
        assert not qualified
        text+='新中心均未通过原四门，未追加参数账户；事前13维完整几何和不适用原因保留。未达标的平滑机制不能视为稳健改进。\n'
    achieved=bool(substantive)
    text+=f"\n原32点平均仓位不同{diagnosis['mean_target_difference_days']:.3f}天，2023平均不同{diagnosis['mean_2023_target_difference_days']:.3f}天；首次分歧分类{diagnosis['first_divergence_counts']}。这些不是单参数因果贡献或增量收益。\n"
    text+='\n## 验证、结论和下一步\n\n'
    text+=f"2新业务中心、3次实际评价（含串行/spawn技术重复）、3中心复用；新参数业务{business}、实际评价{actual}、旧参数复用{reused}；总新业务{2+business}、总实际评价{3+actual}。\n\n"
    text+='合成前缀因果性/未来修改、L个严格过去有限估计/当前排除/阈值等号/基准区别、原bull特征/确认/退出、warmup与非法输入验证，公开实际配置认证加载、Ruff。两个新中心账户独立由绑定Close重算ACF20、严格过去L基准、居中值及全入场/退出状态；完整账户现金/数量/费用/周期/尾仓/年度收益与共同基准对账，若执行参数面板另核对逐点经济与现金；代表串行/spawn信号及双方5账本精确一致。未做仓库全量回归。FULL核验关联证据完整性。\n\n'
    text+=('本轮有限点集内有保持原四门、相对退化和绝对尾部同时改善的方案；反复搜索偏差仍在。' if achieved else '本轮对照完成，未证明保持原四门的实质参数敏感性改善，总目标未达成。')+'\n\n'
    text+='下一步按完整账户及同坐标配对判断短聚合有无有效信息；若没有，保留原绝对门与基准适应的反证，重新定位有效入场信息。原经济目标保持。未推进正式阶段四、冻结、PTE或生产。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery','objective_achieved':achieved,
        'improvement_labels':substantive,'relative_degradation_improvement_labels':relative,'new_qualified':len(qualified),
        'new_mechanism_business_accounts':2,'mechanism_actual_evaluations':3,'new_parameter_business_accounts':business,
        'parameter_actual_evaluations':actual,'reused_parameter_accounts':reused,'report_sha256':file_hash(path),
        'original_economic_criteria':'unchanged; diagnostics do not change center qualification'})
    print({'report':'COMPLETE','qualified':qualified,'objective_achieved':achieved})


if __name__=='__main__':
    main()
