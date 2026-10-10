"""Report short bear ACF aggregation against all prospective controls."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    diagnosis=read(RUNS/'previous_path_diagnosis.json')
    text='''# S013：近期均值ACF门与原转换价格门组合对照

RSCH阶段三，用户授权自主研究无需逐轮评审；COMPLETE仅指本轮证据交付。

## 已有证据、机制和最强反证

原C2132中心通过四门，年化16.1572%、全窗回撤14.1599%；同13维32点收益Q10仅5.8974%、回撤Q90达30.5044%，没有证明稳健。EX012原确认不能缓解bear ACF/H脆弱性；EX013删项和后续平滑、条件期限/保护等负面证据保留。

EX028近期均值居中门年化13.5405%、123笔、2022+11.4638%/2023+0.5481%，原四门只因2024年度回撤19.7899%高于基准18.5736%失败。此前EX020转换价门降低原中心全窗回撤但仅108/109笔交易、低于110笔要求。这不是两个机制可叠加收益的证明；本轮在新账户前声明完整组合，检验信息互补。

两个新中心N0/N1保留EX028 current bear ACF20减严格过去L个估计均值的门，L=confirmation.lookback，原阈值0.1比较相关系数差值。同一参数现同时作用确认与基准，新耦合披露；原bullACF/确认/快速raw路线/区间/期限与所有退出保持。

只在raw bear转bull边界、空仓且原eligible机会成立时，再要求N0当日Close>上一日Close，或N1当日Close>Open，均AND原确认分。等号拒绝；stablebull/bear不加价门，无等待锁存。bear持仓切rawbull只按旧规则退出，下一稳定bull机会不补价门。价门先于原score拒绝理由；所有旧持仓优先级保持。原EX020价格语义精确复用，未新增价格阈值或年份例外。

原TIME、EX028mean-center、EX020CLOSE/BODY四个完整控制复用，总六格仅2新中心。任一新中心通过四门，原TIME32点精确复用，两个新价门中心和旧mean-center各32完整新参数账户（96新），其中未达标者仅事前对称诊断，不登记。旧mean源码复制到mean_reference并完整冻结，保留原身份，不用新价门源码冒充。所有13数值中心及全部32坐标相同；旧CLOSE/BODY不追加参数。

最强反证：新bear入场路径下价格门可能无效、删除好机会、抹掉2023小幅盈利或频率余量；参数H整数、阈值与路线仍可能脆弱。不能把缺口小、中心达标或相对退化小当成实质改善。已见EX012..28的开发池反复搜索，不是独立验证，不新增条件去修某笔2024亏损。

前期32账户描述诊断表明多数首次仓位分歧发生在退出；联合多维扰动不能单独识别某参数因果贡献。新组合仍须完整现金与路径回放。热身max(parent,L+21,W+2)，中心180、原13完整域保持；公共准备仅用授权S013既有资产，缺失明确失败不下载。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp、策略与可执行LimitBuyHold均1%买入溢价。原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤和参数诊断不新增经济门。

## 六个完整中心账户

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
        text+='新中心均未通过原四门，未追加参数账户；事前13维完整几何和不适用原因保留。未达标组合不能视为稳健改进。\n'
    achieved=bool(substantive)
    text+=f"\n原32点平均仓位不同{diagnosis['mean_target_difference_days']:.3f}天，2023平均不同{diagnosis['mean_2023_target_difference_days']:.3f}天；首次分歧分类{diagnosis['first_divergence_counts']}。这些不是单参数因果贡献或增量收益。\n"
    text+='\n## 验证、结论和下一步\n\n'
    text+=f"2新业务中心、3次实际评价（含串行/spawn技术重复）、4中心复用；新参数业务{business}、实际评价{actual}、旧参数复用{reused}；总新业务{2+business}、总实际评价{3+actual}。\n\n"
    text+='合成前缀因果性/未来修改、严格过去均值/两价门低等高/稳定与转换状态/持仓退出优先级、原bull特征/确认/退出、warmup与非法输入验证，公开实际配置认证加载、Ruff。两个新中心账户独立由绑定Close重算ACF20、严格过去L基准、居中值、上一raw路线和价门及全入场/退出状态；完整账户现金/数量/费用/周期/尾仓/年度收益与共同基准对账，若执行参数面板另核对逐点经济与现金；代表串行/spawn信号及双方5账本精确一致。未做仓库全量回归。FULL核验关联证据完整性。\n\n'
    text+=('本轮有限点集内有保持原四门、相对退化和绝对尾部同时改善的方案；反复搜索偏差仍在。' if achieved else '本轮对照完成，未证明保持原四门的实质参数敏感性改善，总目标未达成。')+'\n\n'
    text+='下一步按完整账户及同坐标配对判断组合价门是否改善近期均值ACF账户；若没有，保留不互补的反证，优先定位退出时机对参数变化的影响。原经济目标保持。未推进正式阶段四、冻结、PTE或生产。\n'
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
