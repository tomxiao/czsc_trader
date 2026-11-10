"""Render the authorized three-candidate assessment from completed public evidence."""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((WORK / name).read_bytes())


def pct(value):
    return f"{value*100:.4f}%"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"]*len(headers)) + " |",
        *["| " + " | ".join(map(str,row)) + " |" for row in rows]])


def main():
    scope = read("protocols/scope.json")
    assessment = read("others/assessment_summary.json")
    execution = read("others/assessment_execution.json")
    ranking = read("others/research_nar_ranking.json")
    temporal = read("others/assessment_temporal.json")
    accounts = read("others/account_results.json")
    account_summary = read("others/account_summary.json")
    parity = read("others/center_parity.json")
    audit = read("others/semantic_audit.json")
    stats = read("others/statistics_summary.json")
    bootstrap = read("others/statistics_bootstrap.json")
    native = read("others/comparison.json")
    resource_amendment = read("protocols/resource_amendment.json")
    attempts = read("others/account_attempts.json")
    old_resources, new_resources = (resource_amendment[k] for k in ("old_resources","new_resources"))
    assert attempts[0]["resources"] == old_resources and attempts[-1]["resources"] == new_resources
    assert old_resources["random_seed"] == new_resources["random_seed"]
    assert all(x["resources"]["native_threads"] == 1 for x in attempts)
    resource_rows = [[x["attempt"],x["status"],x["resources"]["workers"],x["resources"]["batch_size"],
        x["resources"]["native_threads"],x["equity_statistics"]["candidate_runs"],
        x["equity_statistics"]["benchmark_runs"],f"{x['elapsed_seconds']/60:.2f}"] for x in attempts]
    assert execution["status"] == "COMPLETED" and accounts["status"] == "COMPLETE"
    assert stats["verification"] == "PASSED" and parity["status"] == "PASS"
    assert len(accounts["accounts"]) == 244 and len(assessment["candidates"]) == 3
    assert len(scope["deferred"]) == 18 and all(x["business_rules"] == "PASS" for x in audit["results"])
    assert all(x["serialized_targets_exact"] == "PASS" and x["maximum_target_rounding_error"] <= 5.01e-11
        for x in audit["results"])
    assert assessment["qualified_nar_ranking"] == ranking["ranking"]
    paths = {x["candidate"]["candidate_id"]:x for x in temporal["candidates"]}
    native_rows = {x["candidate"]["candidate_id"]:x for x in native["rows"]}
    target_names = {"center-nar":"中心NAR", "center-calmar":"中心Calmar", "center-risk":"中心MDD",
        "center-relative-risk":"中心相对MDD", "center-frequency":"闭合频率中位数", "center-coverage":"频率覆盖率",
        "parameters":"参数邻域", "stress-nar":"压力NAR", "stress-calmar":"压力Calmar",
        "stress-risk":"压力MDD", "stress-relative-risk":"压力相对MDD", "stress-zero-risk":"零回撤基准条件"}
    status_text = {"PASSED":"通过", "FAILED":"未通过", "NOT_APPLICABLE":"不适用"}
    center_rows, parameter_rows, pressure_rows, time_rows, acceptance_rows, native_table = [],[],[],[],[],[]
    level_rows, atr_rows, original_gate_rows = [], [], []
    selfcheck_failed_gate_names = set()
    axis_names = {"weak_fraction":"弱参与仓位", "quiet_fraction":"安静期仓位",
        "participation_threshold":"成交参与阈值", "trail_atr":"ATR退出倍数"}
    for candidate in assessment["candidates"]:
        full_id = candidate["candidate"]["candidate_id"]
        cid = full_id.removeprefix("S019-")
        center, parameter, pressure = (candidate[x] for x in ("center","parameter","stress"))
        assert parameter["required_points"] == parameter["valid_points"] == 80
        assert parameter["pass_rate"] == account_summary["groups"][cid]["joint_pass_rate"]
        assert not candidate["coverage_gaps"]
        frequency = candidate["frequency_coverage"]
        center_rows.append([cid,pct(center["nar"]),pct(center["mdd"]),f"{center['calmar']:.6f}",
            candidate["diagnostics"]["FREQUENCY_MEDIAN"],pct(frequency["covered_windows"]/frequency["total_windows"])])
        parameter_rows.append([cid,pct(parameter["pass_rate"]),f"{parameter['joint_passes']}/80",
            pct(parameter["minimum_nar"]),pct(parameter["maximum_mdd"]),f"{parameter['minimum_calmar']:.6f}",status_text[parameter["status"]]])
        levels = account_summary["groups"][cid]["parameter_level_diagnostics"]
        assert set(levels) == set(axis_names)
        points = [r for r in accounts["accounts"].values() if r["parent"] == cid and r["label"].startswith("P")]
        assert len(points) == 80
        atr_center = levels["trail_atr"][1]["value"]
        eligible_center = eligible_side = 0
        for row in points:
            metrics = row["candidate"]
            gates = {"nar": metrics["nar"] >= .55, "calmar": metrics["calmar"] >= 5,
                "absolute_dd": metrics["drawdown"] <= .25,
                "relative_dd": metrics["drawdown"] <= .8*row["benchmark"]["drawdown"],
                "frequency_median": metrics["frequency_median"] >= 6,
                "frequency_coverage": metrics["frequency_coverage"] >= .9}
            assert gates == metrics["gates"] and all(gates.values()) == metrics["eligible"]
            selfcheck_failed_gate_names.update(k for k,v in row["selfcheck_gates"].items() if not v)
            if all(gates.values()):
                if row["parameters"]["trail_atr"] == atr_center:
                    eligible_center += 1
                else:
                    eligible_side += 1
        original_gate_rows.append([cid,eligible_center+eligible_side,eligible_center,26,eligible_side,54])
        for axis, label in axis_names.items():
            slices = levels[axis]
            assert len(slices) == 3 and [x["n"] for x in slices] == [27, 26, 27]
            assert [x["value"] for x in slices] == sorted(x["value"] for x in slices)
            assert abs(sum(x["n"]*x["joint_pass_rate"] for x in slices)-parameter["joint_passes"]) < 1e-10
            level_rows.append([cid,label + f" ({axis})", *[
                f"{x['value']:.8g} / {x['n']} / {pct(x['joint_pass_rate'])}" for x in slices]])
        for point, direction in (("P002", "−5%"), ("P005", "+5%")):
            row = accounts["accounts"][f"{cid}_{point}"]
            metrics = row["candidate"]
            atr_rows.append([cid,direction,f"{row['parameters']['trail_atr']:.8g}",
                pct(metrics["nar"]),pct(metrics["drawdown"]),f"{metrics['calmar']:.6f}",
                "通过" if row["selfcheck_pass"] else "未通过"])
        stress_checks = [x for x in candidate["target_checks"] if x["target"]["target_id"].startswith("stress-")]
        pressure_rows.append([cid,pct(pressure["nar"]),pct(pressure["mdd"]),f"{pressure['calmar']:.6f}",
            "通过" if all(x["status"] in ("PASSED","NOT_APPLICABLE") for x in stress_checks) else "未通过"])
        failed = [target_names[x["target"]["target_id"]] for x in candidate["target_checks"] if x["status"] == "FAILED"]
        acceptance_rows.append([cid,status_text[candidate["acceptance_status"]],"、".join(failed) or "无"])
        path = paths[full_id]
        dist,lag = path["rolling_distributions"],path["consecutive_lagging_rolling_windows"]
        time_rows.append([cid,f"{dist['nar_excess']['above_zero']}/46",f"{dist['calmar_excess']['above_zero']}/46",
            f"{100*dist['nar_excess']['median']:.4f}pp",f"{dist['calmar_excess']['q10']:.4f}",
            lag["nar_excess"]["maximum_count"],lag["calmar_excess"]["maximum_count"],
            pct(path["profit_contribution"]["largest_winner_share_of_positive_closed_pnl"])])
        raw = native_rows[full_id]
        native_table.append([cid,raw["status"],raw["rank_min"],raw["rank_max"],"仅辅助"])
    ranked = ranking["ranking"]
    assert selfcheck_failed_gate_names == {"calmar"}
    ranking_table = table(["研究名次","候选","未舍入NAR的显示值","精确同值数量"],
        [[x["rank"],x["candidate"]["candidate_id"].removeprefix("S019-"),pct(x["nar"]),x["tied_candidates"]] for x in ranked]) if ranked else "本批达标研究排序为空。"
    conclusion = (f"本批三个候选中{len(ranked)}个通过全部原目标，达标后的研究排序为"
        + "、".join(x["candidate"]["candidate_id"].removeprefix("S019-") for x in ranked) + "。") if ranked else "本批三个候选均未通过全部原目标，达标研究推荐集合为空。"
    annual_rows = []
    for year in ("2022","2023","2024","2025","2026"):
        rows = [next(y for y in paths["S019-"+cid]["years"] if y["window_id"]==year) for cid in scope["selected"]]
        assert len({x["benchmark"]["period_return"] for x in rows}) == 1
        annual_rows.append([year + ("（截至10月30日）" if year=="2026" else ""),
            *[pct(x["strategy"]["period_return"]) for x in rows],pct(rows[0]["benchmark"]["period_return"])])
    intervals = []
    for item in bootstrap["comparisons"]:
        n,c,dd = item["cagr"],item["calmar"],item["max_drawdown"]
        intervals.append([item["champion_id"]+" − "+item["comparator_id"],
            f"[{100*n['lower_95']:.2f}, {100*n['upper_95']:.2f}]pp",
            f"[{c['lower_95']:.4f}, {c['upper_95']:.4f}]",
            f"[{-100*dd['upper_95']:.2f}, {-100*dd['lower_95']:.2f}]pp"])
    selection = stats["selection_summary"]
    completion = stats["completion"]
    pbo = stats["sharpe_proxy"]["PBO_SHARPE_PROXY"]
    pbo_text = pct(pbo["pbo"]) if pbo["status"] == "AVAILABLE" else str(pbo)
    dsr_rows = []
    for cid in scope["selected"]:
        value = stats["sharpe_proxy"]["DSR_SHARPE_PROXY_"+cid]
        dsr_rows.append([cid, pct(value["RAW"]["probability"]) if value["RAW"]["status"]=="AVAILABLE" else value["RAW"]["status"],
            pct(value["EFFECTIVE"]["probability"]) if value["EFFECTIVE"]["status"]=="AVAILABLE" else value["EFFECTIVE"]["status"]])
    lines = ["# S019阶段四首批：C0367、C0355、C0264", "Status: COMPLETE；RSCH；本批授权范围3项，另18项未检。",
        "## 结论与正式研究排序", conclusion,
        "原目标保持NAR≥55%、Calmar≥5及原MDD、频率、自检条件。先按全部12项目标完成验收，再按未舍入标准NAR降序；精确同值并列，显示顺序中的ID不构成收益之外的选型条件。",
        table(["候选","本批研究验收","失败项目"],acceptance_rows), ranking_table,
        "下一步建议回到阶段二，以C0355为对照，优先研究ATR硬退出与成交参与阈值引发的仓位跳变，结合四轴联合响应及实际退出路径检验结构改进。原硬门保持，剩余6轮优化额度保留；新研究范围与阶段推进待用户确认。",
        "用户决定后续阶段及其余候选的自检范围；尚余6轮优化额度保留。本轮完成自检与比较，后续冻结另待精确批准。",
        "## 授权范围与样本", "承接[CANDIDATES/6授权子集](protocols/scope.json)、[事前方案](protocols/plan.md)及MANDATE/2。完整21个交接对象保持，本次只评价C0367、C0355、C0264；其余18项状态为NOT_ASSESSED："+"、".join(scope["deferred"])+"。",
        "2021预热，2022-01-03至2026-10-30连续评价，1212交易日、15702个M30决定时点；沿用本地MU/SOXX数据、HFQ整数单位、10万美元、每侧0.1%费用及原限价买入/市价卖出合同。全部历史已参与开发，独立前瞻证据尚待后续安排。",
        "## 中心绩效", table(["候选","NAR","MDD","Calmar","60日闭合中位数","至少3笔窗口覆盖率"],center_rows),
        "中心门槛：NAR≥55%、Calmar≥5、日末MDD≤25%且≤同费买持MDD的80%；滚动60日闭合中位数≥6，至少3笔的窗口比例≥90%。均按未舍入数据验收。",
        "## 参数敏感性与费用压力", "每中心采用四个有效连续参数的中心、上下5%完整三档笛卡尔组合，剔除整体中心，各80点。离散整数的最小合法步长超过5%时保持中心，类别结构固定；因此期限与结构选择风险另行保留。搜索提议网格未用作连续参数真实业务边界。",
        "邻域点联合条件为NAR≥50%、Calmar≥4.5、MDD≤同费买持90%，联合通过率≥80%；全部点MDD≤25%。所有240点完整保留。",
        table(["候选","联合通过率","实际通过/全部","最低NAR","最高MDD","最低Calmar","邻域验收"],parameter_rows),
        "四轴分档表每格依次为参数值 / 点数N / 联合通过率。每行将同一完整80点按该轴取值分成三组，其余三个轴仍联合变化；上下档各27点，中心档因剔除整体中心为26点。各轴重复描述同一批账户，属于完整联合点集内的条件切片，用于观察敏感区间和参数配合；独立因果效应另需专门识别。本表新增回放为0。",
        table(["候选","参数轴","下5%：值 / N / 通过率","中心：值 / N / 通过率","上5%：值 / N / 通过率"],level_rows),
        "按账户原始未舍入指标重新计算中心六门（NAR≥55%、Calmar≥5、两项MDD、两项频率），得到以下诊断。该表采用中心六门，邻域正式验收仍使用前述单点自检条件。",
        table(["候选","80邻点中心六门通过数","ATR中心层通过数","ATR中心层N","ATR上下侧层通过数","ATR上下侧层N"],original_gate_rows),
        f"240个邻域点中，原六门通过合计{sum(x[1] for x in original_gate_rows)}点，其中ATR上下5%侧层的162点通过{sum(x[4] for x in original_gate_rows)}点；全部未通过单点自检的经济指标缺口均为Calmar。此处支持优先研究退出触发与再入场路径的机制敏感性，同时四轴条件切片保留仓位及参与阈值配合造成的联合响应。复算直接使用[账户结果](others/account_results.json)的绩效、买持与参数字段。",
        "为联系实际退出路径，以下另列完整点集中其余三个轴固定在中心的纯ATR两点（P002、P005）。它们与上表整档切片的条件不同，联合稳健性仍由完整80点共同决定。仓位与参与阈值变化的条件分布也一并保留，退出路径解释与四轴联合结果共同用于判断脆弱性。",
        table(["候选","纯ATR扰动","ATR倍数","NAR","MDD","Calmar","单点联合条件"],atr_rows),
        "实际入场一致性、退出时点变化及收益差集中日期见[退出路径诊断](others/exit_diagnostics.md)；该诊断复用上述固定自检账户，新增回放为0。",
        "费用压力保持中心参数，将每侧费用由0.1%加至0.2%，额外滑点仍为0。要求NAR≥50%、Calmar≥4.5、MDD≤25%且严格低于同压力买持；零回撤买持条件保留原定义。",
        table(["候选","压力NAR","压力MDD","压力Calmar","压力验收"],pressure_rows),
        "完整逐点身份、原始账户与分位数见[账户结果](others/account_results.json)、[账户摘要](others/account_summary.json)和[12项目标检查](others/assessment_summary.json)。",
        "## 时间稳定性与盈利集中性", "按252交易日、步长21计算46个重叠窗口，窗口起点沿用前日权益及原持仓。连续落后统计指相邻滚动窗口序列，窗口之间相关。NAR超额为策略减买持的年化收益差；Calmar超额为两者比率之差。",
        table(["候选","NAR胜买持","Calmar胜买持","NAR超额中位数","Calmar超额Q10","NAR最长落后窗口","Calmar最长落后窗口","最大单笔盈利贡献"],time_rows),
        table(["年度",*scope["selected"],"买持"],annual_rows),
        "年度表展示实际期间收益，2026截至10月30日；逐年年化NAR、MDD、Calmar和完整窗口路径另存证据。MAX_SINGLE用最大一笔盈利闭合交易的净利润除以全部盈利闭合交易净利润总和，资金复利规模影响金额贡献。时间与集中性用于解释风险，本轮沿用原约定。详见[时间与贡献证据](others/assessment_temporal.json)。",
        "## 统计不确定性与研究族选择风险", "SE公共配对平稳Bootstrap采用10000次、平均块长21交易日、seed20261110。以下为条件95%区间；MDD一列统一转为正数回撤幅度之差。",
        table(["差值方向","NAR差95%区间","Calmar差95%区间","MDD幅度差95%区间"],intervals),
        "区间反映已选配置与既有样本的重采样敏感性，重采样改变时间顺序。逐项结果见[六组配对统计](others/statistics_bootstrap.json)。",
        f"研究族统计纳入{completion['published_accounts']}份原始评价、{completion['unique_implementations']}个精确实现。原六项中心硬门后按NAR选择的年度回看共{selection['planned_windows']}组；{selection['selected_windows']}组有选择、{selection['no_eligible_windows']}组无合格对象，后续观察{selection['passed_observations']}项通过、{selection['failed_observations']}项失败。它描述固定已见研究族的回顾性稳定性。",
        f"辅助Sharpe-CSCV PBO为{pbo_text}。DSR原始计数与相关性有效计数分别保留：",table(["候选","原始计数DSR","有效计数DSR"],dsr_rows),
        "这些Sharpe代理统计用于提示选择风险；实际NAR加原硬门及人工自适应研究的选择偏差仍按统计说明标为未量化。原始清单、重复实现、口径及限制见[统计汇总](others/statistics_summary.json)与[统计说明](others/statistics_report.md)。",
        "## 执行、证据及排序契约", "本轮新增244个策略账户：240邻域、3压力、1个C0264标准中心复算；复用C0367/C0355两个原中心。C0264原账户携带此前邻域派生绑定，为保留原谱系，在公共接口下执行标准中心并与旧账户进行完整经济parity，结果PASS。见[中心核对](others/center_parity.json)。优化额度仍余6轮，新增搜索提议0。",
        f"按用户授权，账户进程由{old_resources['workers']}升至{new_resources['workers']}，每批账户数由{old_resources['batch_size']}升至{new_resources['batch_size']}，各进程均1个原生线程；随机种子保持。资源来源见[资源变更记录](protocols/resource_amendment.json)，实际执行分段如下：",
        table(["执行段","状态","进程数","每批账户","各进程原生线程","策略回放","买持回放","记录耗时/分钟"],resource_rows),
        "已发表账户与完整计算检查点按原身份复用，原目标、样本及完整点集保持。分段统计见[实际执行记录](others/account_attempts.json)。",
        f"账户累计执行记录{accounts['elapsed_seconds']/60:.2f}分钟，正式SE聚合{execution['seconds']:.2f}秒。代表业务核验覆盖{len(audit['results'])}个账户、{sum(x['decisions'] for x in audit['results']):,}条决定，全部PASS，见[业务核验](others/semantic_audit.json)。",
        "首轮语义审计发现目标仓位的保存精度差异：公共账户序列化沿用pandas.to_json默认十位小数，例如0.16417603125000002保存为0.1641760313。重审先核对5.01×10⁻¹¹舍入界限，再独立重建各账户全部目标仓位并按相同格式序列化，与原保存目标逐值严格相等。经济账户、策略参数及验收门槛保持原值；初次失败保留于[审计技术记录](others/semantic_audit_initial_failure.md)。",
        "正式面板有246份账户事实、240个派生绑定及三套完整邻域，12项目标直接承接MANDATE/2。研究族诊断独立归档，原生面板相应family字段保留FAMILY_RETURN_MATRIX_NOT_SUPPLIED标记。",
        "现行阶段四交付模型要求携带原生comparison。其12项验收结果按原值使用，原生多指标名次原样归档为辅助工具结果；最终推荐与排名唯一采用[纯NAR研究排序](others/research_nar_ranking.json)。该文件绑定目标、请求、面板、原生比较和研究脚本哈希。辅助名次如下：",
        table(["候选","native状态","辅助rank_min","辅助rank_max","用途"],native_table),
        "三者使用相同四轴业务域、相对±5%规则和完整80点组合；独立核对每轴规范化坐标在浮点表示容差内为−0.05、0或+0.05，240点完整覆盖各自笛卡尔积。native严格几何哈希保留实际相对坐标的末位差异，可能给出PARAMETER_METHODS_DIFFER；该原始输出原样保留。研究纯NAR排序依据共同标准账户口径及各自完整12项验收，具体检查见[可比性证据](others/assessment_comparability.json)。",
        "正式交付为ASSESSMENT/2，前驱保留完整CANDIDATES/6及MANDATE/2，本批授权范围另作显式记录。发布采用INTEGRITY校验；研究目标达成状态依上述原门槛验收。见[原生面板](others/panel.json)、[原生辅助比较](others/comparison.json)和[发布校验](others/assessment_publication.json)。"]
    (WORK / "report.md").write_text("\n\n".join(lines)+"\n",encoding="utf-8")
    print("REPORT_READY",len(ranked),"qualified",flush=True)


if __name__ == "__main__":
    main()
