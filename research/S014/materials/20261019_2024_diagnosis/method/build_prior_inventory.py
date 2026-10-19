"""Read S014 historical methods only; no market loading, fitting or account execution."""

from hashlib import sha256
import json
from pathlib import Path
import re

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
EXPERIMENTS = ROOT / "research/S014/experiments"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(name, value):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def walk_refs(value):
    if isinstance(value, dict):
        if value.get("type") == "EvidenceRef":
            yield value
        for child in value.values():
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


# Explicit ref manifests only. No assets inventory, raw quotes or market-data loading.
ref_catalog = {}
for directory in sorted(EXPERIMENTS.glob("EX*")):
    if not 1 <= int(directory.name[2:5]) <= 43:
        continue
    for rel in (
        "others/result.json",
        "protocols/published_design.json",
        "protocols/published_sources.json",
        "others/final_verification.json",
    ):
        path = directory / rel
        if path.exists():
            for ref in walk_refs(read(path)):
                ref_catalog.setdefault(ref["sha256"], []).append(ref)


def locate(experiment, rel, anchor):
    path = EXPERIMENTS / experiment / rel
    raw = path.read_bytes()
    lines = raw.decode("utf-8-sig").split("\n")
    matches = [(i + 1, line.rstrip("\r")) for i, line in enumerate(lines) if anchor in line]
    assert matches, (path, anchor)
    identity = digest(path)
    refs = ref_catalog.get(identity, [])
    if refs:
        resolved = EvidenceRef.from_dict(refs[0]).resolve(ROOT)
        assert resolved.read_bytes() == raw
    result = {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": identity,
        "bytes": len(raw),
        "line": matches[0][0],
        "anchor": anchor,
        "line_excerpt": matches[0][1],
        "line_basis": "LF-delimited bytes, same as rg; trailing CR stripped from excerpts",
        "public_ref": refs[0] if refs else None,
        "public_content_identity_verified": bool(refs),
    }
    return result


specs = [
    {
        "id": "old_price_models_and_direct_entry_confirmations",
        "ex": "EX005_20261016",
        "report": ("protocols/final_report.md", "固定机制对照"),
        "exact_rule": "回落父条件为C>MA60且近5日回落，加当日C>O；突破为C突破前20日High，加量高于前20日均量；另有急跌后收于当日上半区。固定3/5/10日独立尝试，不是C0056资金账户。",
        "negative_and_counterevidence": "回落收阳、突破量确认未支持增量；急跌修复2024仅2个样本，删除最好1例差转负。20日波动对单侧不利跌幅方向跨年变，ATR是幅度参考而非止损保证。",
        "role": "INDEPENDENT_ENTRY_COMPONENTS_NOT_CONTINUOUS_POLICY",
        "repeat_warning": "MA/ATR/反弹修复/量确认已是旧信息，换名字或邻近窗口不能称新机制。",
    },
    {
        "id": "past20_rise_and_profit_single_day_weakening",
        "ex": "EX006_20261016",
        "report": ("protocols/report.md", "8个期限/检查点比较的合并差值全部为负"),
        "source": ("src/attribution.py", '"selected": mark > 0 and ret1 < 0'),
        "exact_rule": "独立H3/H5/H10/H20尝试的买入D/中点D：扣双侧费用估值浮盈>0且当日跌，下一可执行日退出；另描述过去20日上涨/下跌。",
        "negative_and_counterevidence": "8个盈利且单日弱化退出比较合并均负；2024局部改善不能抵消强行情提前退出代价。过去20日涨在2022/25较差、2026较好，不能当作稳定跨年入场状态。",
        "role": "LOCAL_EXIT_PROBE_AND_STATE_DESCRIPTION",
        "repeat_warning": "没有验证一般亏损止损，也没有跨已实现交易的连亏状态。",
    },
    {
        "id": "MA_ATR_peak_and_adaptive_response",
        "ex": "EX007_20261017",
        "report": ("protocols/report.md", "价格结构增量在三个期限的合并均值均为负"),
        "source": ("src/components.py", '"trend_preserved": (close >= ma20) & (ma5 >= ma20)'),
        "exact_rule": "MA20位置、MA5/20排列、MA20五日变化、前5收盘支撑距离/ATR20，及当前浮盈、Close峰值回吐/ATR，在H5/10/20中点一次退出模型/简单探针；另每日扩展、126/252半衰期成熟结果更新入场。",
        "negative_and_counterevidence": "结构增量各期限合并均负，完整组合弱于固定持有；持仓路径H10较基线小正但较固定持有仍负。近期模型不及简单近期均值和全部参与。",
        "role": "HOLDING_COMPONENTS_AND_MATURE_LABEL_MODELS",
        "repeat_warning": "模型近期结果更新不等于实际账户连亏后暂停；新动作职责只能另行明确检验，不能宣称出现新MA/ATR/峰值输入。",
    },
    {
        "id": "market_sector_state_models",
        "ex": "EX010_20261017",
        "report": ("protocols/report.md", "新增行业日内/隔夜、1/5/20日"),
        "exact_rule": "股票与市场/行业1/5/20日收益、波幅、隔夜盘中响应及截至T-1的60日共同回归，在固定岭/树收益预测中做增量。",
        "negative_and_counterevidence": "行业滞后有局部线索，被更强股票滞后对照削弱；3日当前行业组合多数增量负。不能称外部趋势已经解决入场或亏损退出。",
        "role": "PREDICTION_COMPONENT_NOT_C0056_ACTION_GATE",
        "repeat_warning": "同一已知市场特征换作订单职责是新动作假设，不是新信息；换20日窗口本身不构成新机制。",
    },
    {
        "id": "H3_causal_environment",
        "ex": "EX013_20261017",
        "report": ("protocols/report.md", "直接排除低状态相对保留所有父机会"),
        "source": ("src/features.py", "out['ma_slope']"),
        "exact_rule": "低开收阳父机会内，20日缺口序列相关与每年成熟H3训练中位数做环境分层；同时普查收缩扩张、市场行业同步、吸收等信息。",
        "negative_and_counterevidence": "高低H3相对环境用途有有限支持；2023匹配反例、2025高组仍亏、全序列不单调。排低状态原标签有平均增量，尚非资金账户入场门。",
        "role": "BOUNDED_RELATIVE_ENVIRONMENT_COMPONENT",
        "repeat_warning": "高环境不是普遍上涨/安全状态；原阈值包含年度成熟校准，不是无拟合固定零界规则。",
    },
    {
        "id": "common_decline_and_loss_diagnostics",
        "ex": "EX014_20261017",
        "report": ("protocols/report.md", "匹配31个高风险腿行情簇等权"),
        "exact_rule": "在固定H3高环境独立尝试内比较20日下行波动占比、修复未完成、下跌日成交量占比、市场行业过去5日同跌；-3%仅诊断损失线。",
        "negative_and_counterevidence": "共同下跌原损失关联随匹配/簇等权及去重反号；其他三项原风险方向未获支持。低环境H1延H3有风险参考，但没有新入场门/止损账户。",
        "role": "RISK_STATE_DIAGNOSTICS_NOT_STOP_LOSS_POLICY",
        "repeat_warning": "不能把-3%诊断线说成已测止损，也不能把市场同跌原始关联包装成已验证禁买条件。",
    },
    {
        "id": "entry_day_failed_repair_probes",
        "ex": "EX015_20261017",
        "report": ("protocols/report.md", "四个首次买入日收盘条件均未支持改善H3持有"),
        "exact_rule": "已实际买入D的C低于原signal O、C低于原signal C、股票日内弱于大盘、越过前高但收在当日下半区，分别下一日退出与固定H3比较。",
        "negative_and_counterevidence": "四条件每个已成交父机会差-0.2272/-0.4206/-0.1677/-0.1813pp；无新增有效组件。最后一条件不是严格突破失败，也不能定位High发生在买入后。",
        "role": "LOCAL_FIRST_CLOSE_EXIT_PROBE_NOT_ACCOUNT",
        "repeat_warning": "不能把一般‘买后不涨/反弹失败’当作未试新口号；但不等同Z5>2且当前亏损的人口。",
    },
    {
        "id": "environment_and_entry_filters_in_accounts",
        "ex": "EX018_20261017",
        "report": ("protocols/account_report.md", "据此锁定2×2×2"),
        "exact_rule": "低开收阳/仅收阳 × 原高环境/全部环境 × H3/H6，共8资金账户格（其中2复用）；EX017原高低期限交互为先行完整账户。",
        "negative_and_counterevidence": "全8原目标通过0；环境作用依赖入场和期限。EX017的2024四旧路径收益均正，不可说2024任何老策略皆无机会；它们在2021/22/25等仍失败。",
        "role": "COMPLETE_FUNDED_ENTRY_ENVIRONMENT_ACCOUNTS",
        "repeat_warning": "不按2024选旧赢家切换策略，不能忽略其他年份代价；这些不是C0056的新退出职责。",
    },
    {
        "id": "support_entry_start_phase_and_reservation",
        "ex": "EX023_20261018",
        "report": ("protocols/account_report.md", "R−C检验限制提前退出后的重新入场"),
        "exact_rule": "C0056原支撑入场、破支撑次日卖、原真实entry+10再入场预约；EX021比较支撑门/固定H10/无预约早退，EX022只改变首次启动delay0..10。",
        "negative_and_counterevidence": "支撑入场有限长期改善、预约R较即时C全期显著改善，但R2024-27.32%、全部原目标未达。首次delay不是每次亏损后的冷却。",
        "role": "COMPLETE_ACCOUNT_TIMING_AND_RESERVATION",
        "repeat_warning": "保留原预约是已测强上下文；新跳过买入不能伪造真实entry锚点或把未成交记亏损。",
    },
    {
        "id": "first_support_profit_or_loss_exit",
        "ex": "EX024_20261018",
        "report": ("protocols/account_report.md", "C0058：首次破坏时P≤0才提前退出"),
        "exact_rule": "P/N互补：仅首次严格早于deadline支撑破坏判断含买费P>0或<=0；不符则整个剩余cycle忽略support直到原H10。P不含未来卖费，零归N，不每日重判。",
        "negative_and_counterevidence": "P有限正退出增量须保留，但未全部达标；N整体弱于R。2024 P约-14.71%、N约-27.31%；不能称亏损才卖已解决。",
        "role": "COMPLETE_ACCOUNT_FIRST_BREAK_ONCE_CONDITIONAL_EXIT",
        "repeat_warning": "N不是不依赖support的任意亏损止损，更不是Z5>2不论P退出；两个人口/时点不同。",
    },
    {
        "id": "positive_candle_entry_gate",
        "ex": "EX025_20261018",
        "report": ("protocols/account_report.md", "B/R在2024由亏转盈的局部改善被其他年度损伤覆盖"),
        "exact_rule": "原空仓支撑BUY候选D额外要求当日HFQ C>O，分别配B/R/P固定退出规则；持仓阴线不单独卖。",
        "negative_and_counterevidence": "B/R2024变+13.94/+10.64%，但三新账户去2026仍全亏；共同入场少，遗漏旧盈利路径/增加较差路径为主要代价。",
        "role": "COMPLETE_ACCOUNT_ENTRY_GATE_NEGATIVE",
        "repeat_warning": "2024局部改善既不是通用入场有效，也不证明所有新入场职责均无用；新Z gate不能从旧交易删除收益相加代替重跑账户。",
    },
    {
        "id": "P_conditional_reservation",
        "ex": "EX029_20261018",
        "report": ("protocols/account_report.md", "首次严格早于E+9收盘的破坏时"),
        "exact_rule": "原所有support破坏都卖，仅首次P正/非正决定是否保留本周期原entry+10预约；P冻结，不依据最终卖出盈亏、不累计前几笔亏损。",
        "negative_and_counterevidence": "互补预约两组均弱于全部预约R，全目标0/4；部分2024改善但2021/22等损伤，不支持零边界选择等待。",
        "role": "COMPLETE_ACCOUNT_SINGLE_CYCLE_WAIT_RULE",
        "repeat_warning": "不是连亏后暂停；不得把原单cycle浮盈条件改名成跨cycle学习。",
    },
    {
        "id": "old_support_recovery_gate_diagnosis",
        "ex": "EX030_20261018",
        "report": ("protocols/report.md", "不支持把“先收复旧支撑”加入为自动买入过滤条件"),
        "exact_rule": "连续supportbreak首日冻结旧L，后首次滚动合格分C>=L真实/低于L表面；另持续锚点未收复前不重设；对全部机会H10与旧账户69未收复entry做只读诊断。",
        "negative_and_counterevidence": "首次恢复真实减表面H10均值全期-0.6074pp、去2026-1.4238pp，69未收复entry仍正总log贡献；不支持筛掉表面恢复。",
        "role": "NO_NEW_ACCOUNT_OPPORTUNITY_LABEL_DIAGNOSIS",
        "repeat_warning": "‘等反弹确认/收复旧支撑’已被明确诊断，换锚点名不算新信息；也未证明实际gate账户必然更差。",
    },
    {
        "id": "common_down_relative_resilience_loss_hold",
        "ex": "EX033_20261018",
        "report": ("protocols/report.md", "该笔占本轮相对R总增量的90.79%"),
        "exact_rule": "C0056首次破位P<=0，market1d<0、sector1d<0且stock1d>=sector1d，改为等原H10；100已闭合配对中改变10次，不新跑完整账户。",
        "negative_and_counterevidence": "100事件平均+0.3862pp，较简单P少0.3527pp；2024-09-13单例占90.79%，删最大3/5事件负。不能宣称2024行情共同冲击可事前稳定识别。",
        "role": "LOCAL_EXIT_ACTION_LABEL_NOT_FUNDED_POLICY",
        "repeat_warning": "这是亏损时等一等，不是亏损时额外卖；旧支撑已破人口与正Z状态原则上不重合。",
    },
    {
        "id": "EX043_grace_shock_and_giveback",
        "ex": "EX043_20261019",
        "report": ("protocols/design.json", '"hold_rule": "ENTRY_GRACE"'),
        "source": ("src/strategy_runtime/strategies/exante_hold_exit.py", "shock = bool(eligible and feature.shock_known and net_profit > 0 and feature.z5 > 2)"),
        "exact_rule": "ENTRY_GRACE只在实际BUY D豁免support一次；SHOCK_PROFIT在真实held、无既存pending、D<deadline、净P>0、Z5>2时下一执行日卖；不限制support。GIVEBACK须曾净涨>=2ATR且Closepeak回吐>=1ATR，当前可负；TREND只entryD固定MA/ATR保护。",
        "negative_and_counterevidence": "9完整账户2024全负：[-27.3319%,-21.1573%]，最佳GRACE+SHOCK仍失败。TREND2025不启动，不能说它覆盖May30。GRACE+SHOCK的2022/2025改善与2021代价均保留；9路径distinct但非独立样本。",
        "role": "COMPLETE_DATE_FREE_FIXED_POLICY_3X3",
        "repeat_warning": "同Z5在空仓BUY前禁买、或现仓不论P退出均尚未执行；不是新增指标，而是同信息不同持仓人口/决策时点/动作职责。",
    },
]

inventory = []
for spec in specs:
    item = {k: v for k, v in spec.items() if k not in {"ex", "report", "source"}}
    item["experiment"] = spec["ex"]
    item["report_locator"] = locate(spec["ex"], *spec["report"])
    item["source_locator"] = locate(spec["ex"], *spec["source"]) if "source" in spec else None
    inventory.append(item)

patterns = {
    "exact_Z_action": r"z5|shock_profit|ret5_log|sigma20_pre5",
    "cross_cycle_loss_memory": r"loss.?streak|last.{0,15}(?:return|loss)|previous.{0,15}loss|stop.?after|last_trade|last_exit|累计亏|重复亏|连续亏|连亏|连败|停止交易|暂停交易|多次亏",
}
search = {name: [] for name in patterns}
searched_files = []
for directory in sorted(EXPERIMENTS.glob("EX*")):
    if not 1 <= int(directory.name[2:5]) <= 43:
        continue
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or not (
            path.suffix == ".py"
            or (path.suffix == ".md" and "report" in path.name)
            or (path.suffix == ".json" and "design" in path.name)
        ):
            continue
        if "prelock_failures" in path.parts:
            continue
        raw = path.read_bytes()
        rel = path.relative_to(ROOT).as_posix()
        searched_files.append({"path": rel, "sha256": sha256(raw).hexdigest(), "bytes": len(raw)})
        for number, line in enumerate(raw.decode("utf-8-sig").split("\n"), 1):
            for name, pattern in patterns.items():
                if re.search(pattern, line, re.IGNORECASE):
                    search[name].append({"path": rel, "line": number, "excerpt": line.rstrip("\r")})

source = EXPERIMENTS / "EX043_20261019/src/strategy_runtime/strategies/exante_hold_exit.py"
assert digest(source) == "e980a552367e9354a5f2fcfcd411e5c6a64a408ecb83bed115aa9b578029e57a"
findings = ROOT / "research/S014/materials/20261019_exante_hold_exit/accounting/research_findings.json"
assert digest(findings) == "376615f80ddbce27ec5dac39b465d55d8cd18b3a8e8a77a6528bb36c36e1c5a3"

result = {
    "status": "READ_ONLY_PRIOR_METHOD_REVIEW_COMPLETE_NO_NEW_POLICY_EXECUTION",
    "identity": "RSCH",
    "branch": "codex/s014-jinniu-research",
    "baseline_head": "89d5e51c7485ecbcf7ef1fd8663adc86d526bb5d",
    "historical_scope": "S014 only EX001..043 and explicitly listed existing S014 material; no other research batch or memory",
    "line_basis": "LF-delimited bytes as rg",
    "existing_mechanisms": inventory,
    "exact_Z_conclusion": {
        "prior_complete_policy": "Only EX043 positive-current-net-P SHOCK_PROFIT among reviewed source/report/design files",
        "entry_candidate_Z_gate": "No exact complete account or fixed opportunity-gate evaluation found",
        "held_Z_exit_without_P_guard": "No exact complete account or eligible population evaluation found",
        "not_new_information": "same old price-only Z5 and same fixed >2; new proposals change population, timing, and action only",
        "N_not_same": "EX024 N requires first supportbreak, once-frozen P<=0; positive Z5 implies C_D>C_D-5 and cannot coincide with strict S5 downside break when sigma is finite positive",
        "case_limit": "Root/B targeted Oct8/9 observation motivates a hypothesis only. This review does not recompute those features or infer an entry-gate account value from the current-inventory loss.",
    },
    "cross_cycle_loss_pause": {
        "finding": "No exact funded rule using consecutive actual completed net losses and a finite pause/restart found in the searched source/report/design scope",
        "not_equivalent": ["EX007 mature-label adaptive prediction", "EX022 initial-only delay", "EX023 fixed reservation independent of profit", "EX029 first-break current-cycle frozen P"],
        "D_known_needed_if_later_selected": ["actually completed cycle fills and both-side fees", "net realized loss known only after actual sale", "finite pause unit and fixed restart rule", "reservation and failedBUY distinction", "no retrospective use of future cycle outcome"],
        "current_recommendation": "Keep as a competing explanation; do not add a third factor or run it concurrently before root2024 attribution.",
    },
    "minimal_discriminating_design": {
        "status": "METHOD_RECOMMENDATION_ONLY_ROOT_ATTRIBUTION_AND_FINAL_LOCK_PENDING",
        "baseline": "EX043 ENTRY_GRACE/SHOCK_PROFIT, formal actual run004; original C0056 remains reused context",
        "fixed_information": "Use exact EX043 causal_features Z5/sigma-known masks, threshold2 and original HFQ/in-window membership; no new window, data or fit",
        "factor_A_entry": ["original entry participation", "suppress a new flat BUY intent when known Z5>2"],
        "factor_B_exit": ["original netP>0 AND known Z5>2", "known Z5>2 regardless current P"],
        "four_cells": ["A0 B0 fresh source economic-control exact EX043run004", "A1 B0 entry-gate only", "A0 B1 remove P guard only", "A1 B1 combined actual funded path"],
        "D_known_entry": "after actual D fills: flat, originalready/supportok, original reservation reached, not failedBUYreset; exact D-known Z with positive scale",
        "D_known_exit": "actual held, no inherited prior SELLpending, before originaldeadline; fee-adjusted current P from actualentryfill; D-known Z, not future sell price",
        "suppressed_entry_semantics": "No BUY intent/order/accepted signal, no failedBUY, no phantom entry/deadline/reservation; next D may assess again. Original still-open cycle reservation remains.",
        "exit_priority": "inherited pending/deadline mandatory > selected shock risk exit > ENTRY_GRACE support protection; when gap-filled actual BUY D already loses but Z>2, B1 may plan next-session SELL, never same-day turnover",
        "missing_Z": "preserve existing unknown flags/rawnull; unknown does not satisfy gate or new exit, no zero-filled valid feature/fallback/new data",
        "full_execution": "Original1642-session full window preserves warmup, cash/units/fees/reservations and2026 technicaltail; no date/year rules, no year reset, no forced2025 end sale",
        "economic_evaluation": "All2020..2025 own-opening annual return/drawdown plus original frequency; retain original full-contract metrics as historical context, do not promote a new candidate or change old eligibility",
        "comparisons": "A effect at each B, B effect at each A, combination interaction as descriptive whole-policy return differences. Recompute full cash-funded paths; never add/delete old trade profits to synthesize results.",
        "population_and_attribution": "Count original flat candidateD Z>2 and actualheld Z>2 by current P before economic claims; report covered/uncovered major2024 loss cycles and crossyear triggers. Cases/missed rises/opportunity counts are explanations, not a value label.",
        "control_gate": "new source synthetic/causal/source-identity review; fresh A0B0 exact economic equivalence to EX043run004 plus independent actual-state audit before any other3; technicalfailure retained and stops dependent dispatch",
        "no_economic_stopping_or_search": "Run all4 fixed cells if later authorized regardless gain/loss; no Z/return/ATR threshold sweep, no date/year-specific switch, no no-harm/CI/concentration hardgate",
        "count_is_proposal_not_user_cap": 4,
        "alternative_not_parallel": "If root attribution does not indicate appreciable D-known candidate/held coverage, state that mechanism is not applicable and reconsider role hypothesis; do not shift threshold to hit Oct8/9.",
    },
    "reusable_public_route": {
        "source": "research/S014/experiments/EX043_20261019/src/strategy_runtime/strategies/exante_hold_exit.py",
        "runner": "research/S014/experiments/EX043_20261019/src/run_accounts.py",
        "previous_source_lock": "research/S014/experiments/EX043_20261019/protocols/execution_lock.json",
        "existing_input_route": "EX017 pinned_inputs.get_context existing authenticated offline provider; publicprepare must verify original execution identities/fingerprint and causal plan except new runtime identity",
        "new_identity_required": "If selected later: new experiment/public source+payload identity and unused diagnostic CID, fresh source-specific control; do not mutate EX043 or register formal candidate",
        "not_now": "No experiment allocation, source modification, prepared binding, account dispatch or formal publication performed by this inventory",
    },
    "source_verification": {
        "files_with_public_ref": sum(bool(x[k] and x[k]["public_ref"]) for x in inventory for k in ("report_locator", "source_locator")),
        "source_sha256": digest(source),
        "EX043_findings_sha256": digest(findings),
        "new_market_input_loads": 0,
        "new_market_supplier_calls": 0,
        "new_fits": 0,
        "new_strategy_histories_or_accounts": 0,
        "new_state_PnL_computations": 0,
        "new_platform_or_prod_or_git_mutations": 0,
    },
    "execution_authorized_here": False,
    "next_step": "Root finishes2024 principal-loss attribution and locks or rejects this role2x2 before any new experiment/strategy/account.",
}
write("prior_mechanism_inventory.json", result)
write(
    "search_scope_manifest.json",
    {"scope": "S014 EX001..043 .py plus report.md and design.json-named files; exclude preserved invalid prelock draft", "searched_file_count": len(searched_files), "files": searched_files, "patterns": patterns, "hits": search, "absence_limit": "Bounded source/report/design inventory; no claim of exhaustive semantic proof from keyword absence alone", "raw_market_data_copied": False},
)
write(
    "review_manifest.json",
    {"status": "PASS_DECLARED_HISTORICAL_FILES_AND_ANCHORS", "script_sha256": digest(Path(__file__)), "inventory_sha256": digest(OUT / "prior_mechanism_inventory.json"), "search_manifest_sha256": digest(OUT / "search_scope_manifest.json"), "mechanism_records": len(inventory), "searched_files": len(searched_files), "new_accounts": 0, "new_fits": 0, "new_market_inputs": 0},
)
print("REVIEW_WRITTEN", len(inventory), "mechanisms", len(searched_files), "bounded source/report/design files")
