import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import pandas as pd

ROOT = Path.cwd()
BASE = ROOT / "research/S015/experiments"
LAST = BASE / "EX062_20261024"
assert not (ROOT / "research/S015/deliveries/CANDIDATES/6").exists(), (
    "Preserve published reports and evidence"
)


def read(p):
    return json.loads(p.read_bytes())


def save(p, v):
    p.write_text(
        json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def frozen(p):
    return {"path": p.relative_to(ROOT).as_posix(), "sha256": digest(p)}


def pct(x):
    return f"{x * 100:.4f}%"


spec = importlib.util.spec_from_file_location("publisher", LAST / "src/publish_candidates.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)
rows = {}
results = {}
for n in range(58, 63):
    home = BASE / f"EX{n:03d}_20261024"
    result = read(home / "others/results.json")
    results[n] = result
    assert read(home / "others/audit.json")["status"] == "ARITHMETIC_CHECKS_PASS"
    for row in result["rows"]:
        assert pub.center_pass(row) == row["both_center_pass"]
        rows[row["candidate_id"]] = {"row": row, "experiment": home.name}
passing = {cid for cid, x in rows.items() if x["row"]["both_center_pass"]}
front = pub.frontier(rows)
controls = {"C5807", "C5818", "C6101", "C6102", "C6108", "C6114", "C6128", "C6130"}
selected = passing | front | controls
pathgroups = {}
for cid in sorted(passing):
    r = rows[cid]["row"]
    key = ":".join(r["runs"][w]["equity_sha256"] for w in ("full", "s011_common"))
    pathgroups.setdefault(key, []).append(cid)
allpaths = {
    tuple(x["row"]["runs"][w]["equity_sha256"] for w in ("full", "s011_common"))
    for x in rows.values()
}
summary = {
    "status": "RESEARCH_COMPLETE_PENDING_PUBLICATION",
    "rounds_completed": 5,
    "researcher_round_ceiling": 6,
    "configs": len(rows),
    "formal_accounts": sum(r["formal_accounts"] for r in results.values()),
    "technical_accounts": sum(r["technical_accounts"] for r in results.values()),
    "center_pass_count": len(passing),
    "center_pass_ids": sorted(passing),
    "center_pass_path_groups": list(pathgroups.values()),
    "center_pass_distinct_path_count": len(pathgroups),
    "all_distinct_path_count": len(allpaths),
    "frontier": sorted(front),
    "selected_ids": sorted(selected),
    "selected_count": len(selected),
    "new_fully_qualified": 0,
    "stage4_status": "NOT_AUTHORIZED_NOT_RUN",
    "paths_note": "配对434/415权益float64字节哈希分组，仅描述这些账户的净值；不是独立策略、总体经济等价或未来行为等价证明。",
    "stop": "已回答资金投入、退出与再入场混淆、邻域和边界问题；扩边未形成值得继续优化的新方向。剩余风险主要属于阶段四自检，不继续寻找小数阈值或耗尽轮数。",
    "overview": "当前全量公开概览刷新未返回且已中止；保留历史概览及局部当前核验。交付、候选和所用账户分别经当前公共API验证，不宣称全历史资格已重审。",
}
save(LAST / "others/stage3_summary.json", summary)
table = []
for cid, item in rows.items():
    r = item["row"]
    table.append(
        {
            "candidate_id": cid,
            "experiment": item["experiment"],
            **r["parameters"],
            **{
                w + "_" + m: r["runs"][w][m]
                for w in ("full", "s011_common")
                for m in (
                    "net_return",
                    "cagr",
                    "dd",
                    "closed",
                    "frequency_median",
                    "frequency_good",
                    "fees",
                )
            },
            "joint_center_pass": r["both_center_pass"],
            "frontier": cid in front,
            "retained": cid in selected,
            "content_sha256": r["identity"]["content_sha256"],
        }
    )
pd.DataFrame(table).to_csv(LAST / "others/stage3_grid.csv", index=False, encoding="utf-8")
findings = {
    58: "23配置中C5806（均值中心、3日固定、95%投入）首次通过阶段三联合目标。95%与100%目标序列、成交时点/价格一致，改善来自承担更少资金风险，不是识别入场亏损。1/2/4/5/7日固定持有未提供更好整体解；中位与修复退出对照保留收益风险取舍。",
    59: "24配置中C5901、C5902联合达标，但非fixed规则同时改变了退出和再入场许可，不能把总改善归因早退。C5902确认期=持有上限=3，不可能提前退出；独立重建与固定3日加正步再许可精确等价。C5901只有2次早退，仍混有再许可影响。锚失效、修复封顶和延持没有形成更优整体策略。该混淆已在EX061显式正交拆分，不改写本轮原件。",
    60: "22配置中C6015/16/17/18（投入93/94/96/97%）联合达标。加EX058的95%，观察到93%..97%的离散可行点；92%收益不足，98%回撤失败，不据此证明区间内每点都达标。97%仅靠极小回撤余量通过。lookback2/4/5/7和hold2/3/4交互及中位/日高低中点定义均没有新联合达标，三日尺度敏感性是重要反证。",
    61: "32配置中5个联合达标。显式rearm_mode分离了退出与重新入场：固定3日+正步再许可C6105在100%投入下通过双门；95%版本C6104也通过。即时再入场下单日/两日提前退出均未联合达标；正步再许可下两日早退虽过线，却未优于固定退出。中心定义及持有/观察期邻域没有同时复现全部目标，不能把规则解释为普遍有效。",
    62: "25配置中4个联合达标，均为既有均值n3/h3家族的投入变化。正步再许可固定退出92.5/93/97.5%过线，80%及先前90%收益不足；两日早退93%共同窗口收益91.5363%略低于目标。更长观察期7/10、固定持有7/10/14、锚宽度扩展和repair_cap7/10未形成新的整体优势；后者和5日路径相同。停止继续调参，准备阶段四而非追求更多过线身份。",
}
titles = {
    58: "投入与持有期限",
    59: "持有价值失效及延续",
    60: "达标邻域与价格中心尺度",
    61: "退出与重新入场许可分离",
    62: "边界扩展与阶段三收口",
}
common = "434日原经济与双频率门 AND 415日净收益严格>91.5802915%、回撤严格<7.2486637491%；比较使用原始未舍入值。全部为已见开发样本，两个窗口高度重叠；并非独立验证。"
for n in range(58, 63):
    home = BASE / f"EX{n:03d}_20261024"
    result = results[n]
    lines = [
        f"# S015 EX{n:03d}：{titles[n]}",
        "",
        "Status: COMPLETED",
        "",
        f"RSCH，阶段三，2026-10-24。{findings[n]}",
        "",
        "## 问题、方法与边界",
        "",
        read(home / "protocols/accounts.json")["question"],
        "",
        common,
        "",
        f"本轮{len(result['rows'])}个事前固定配置，Optuna排队四目标回填，4个工作进程、每进程原生线程1、seed13。{result['formal_accounts']}个正式账户，另{result['technical_accounts']}个串行技术对照；技术重复不计作独立配置。未执行阶段四32点联合扰动、完整费用压力或正式排序。",
        "",
        "全部使用原434/415窗口各独立10万元空仓、CYCLE_TARGET/signal_cash_fraction/entry_cycle资金契约，1%限买、市价卖出、100份整手、每侧0.1%、期末不强平。正式运行时钟20:31；EX061主代表另核验17:30计划等价，未证明供应商历史17:30发布/修订可得性。日范围成交不考虑市场成交量，沿用原约定。",
        "",
        "## 全部配置与结果",
        "",
        "| 身份 | 中心/观察期/持有上限/投入 | 退出/确认/再许可 | 434收益/回撤 | 415收益/回撤 | 434滚动60日闭合中位数 | 联合中心 |",
        "|---|---|---|---|---|---:|---|",
    ]
    for r in result["rows"]:
        p = r["parameters"]
        a = r["runs"]["full"]
        b = r["runs"]["s011_common"]
        mode = p.get("rearm_mode", "immediate" if p["exit_mode"] == "fixed" else "positive_step")
        rule = f"{p['exit_mode']}/{p.get('confirmation', '—')}/{mode}"
        if p["exit_mode"] == "anchored_guard":
            rule += f"/锚宽{p['failure_buffer']}"
        if p["exit_mode"] == "extend_repair":
            rule += f"/最迟{p['max_hold']}"
        lines.append(
            f"| {r['candidate_id']} | {p['center_kind']}/{p['lookback']}/{p['hold']}/{p['allocation']:.3f} | {rule} | {pct(a['net_return'])}/{pct(a['dd'])} | {pct(b['net_return'])}/{pct(b['dd'])} | {a['frequency_median']:g} | {'通过' if r['both_center_pass'] else '未通过'} |"
        )
    lines += [
        "",
        "## 解释与验证",
        "",
        findings[n],
        "",
        "所有目标按独立原始指标联合判定；未以收益抵消回撤。账户净值差包含仓位、费用、后续资金及交易队列变化，不将漏掉原账户某笔损益直接当作可实现改善。源码、有效参数和固定规则共同决定候选内容；相同净值路径不视为独立收益机制。",
        "",
        "因果前缀、固定对照和独立账本算术检查通过。公开资金归因仍为UNSUPPORTED，独立算术仅核对现金、持仓、含费周期预算、收益回撤和交易频率，没有伪装成官方机制归因。",
        "",
        "局限：反复选择开发信息、三日尺度敏感、入场亏损及盈利机会遗漏仍存在；本轮中心过线不是稳健性或冻结资格通过。阶段三下一步由完整交付决定，阶段四须用户另批。",
        "",
        "## 证据",
        "",
        "- [事前协议](protocols/accounts.json)及[固定引用](others/protocol_refs.json)。",
        "- [全部结果与Optuna记录](others/results.json)、[因果前缀](others/runtime_checks.json)、[独立账本核验](others/audit.json)。",
    ]
    for name in (
        "focused_review",
        "mechanism_review",
        "rearm_checks",
        "mechanism_report",
        "clock_checks",
        "stage3_audit_summary",
        "uncertainty",
        "stage3_summary",
    ):
        if (home / f"others/{name}.json").exists():
            lines.append(f"- [{name}](others/{name}.json)。")
    (home / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

r = rows["C6105"]["row"]
full = r["runs"]["full"]
commonr = r["runs"]["s011_common"]
lines = [
    "# S015 阶段三交付：价格中心修复与重新入场许可",
    "",
    "Status: COMPLETED",
    "",
    f"阶段三研究工作已完成：EX058—062共5轮、{len(rows)}个配置、252个正式窗口账户及6个串行技术对照。{len(passing)}个配置身份通过当前全部经济与频率中心目标，描述性净值分组为{len(pathgroups)}组；正式自检尚未执行，当前不能称为完整合格策略。",
    "",
    "## 结论与代表",
    "",
    "以C6105作为主要发展代表：完成的30分钟价格取对数均值形成每日价格中心；中心较3个交易日前上移、收盘低于当日中心时允许买入，持有3个信号日后退出。每次退出后先等至少一次中心较前日上移，再重新允许入场。许可会保持到下一次退出，入场当日本身可以再次回落；退出当日不重新许可或重新入场。首个周期默认已许可。每个周期投入当时可用现金100%，含费预算锁定后只补剩余目标。",
    "",
    "| 账户 | 净收益 | 最大回撤 | 年化收益 | 闭合交易 | 60日中位数 | 至少3笔窗口 |",
    "|---|---:|---:|---:|---:|---:|---:|",
]
for w in ("full", "s011_common"):
    a = r["runs"][w]
    lines.append(
        f"| {'434日' if w == 'full' else '415日'} | {pct(a['net_return'])} | {pct(a['dd'])} | {pct(a['cagr'])} | {a['closed']} | {a['frequency_median']:g} | {a['frequency_good']}/{a['frequency_windows']} |"
    )
lines += [
    "",
    f"415日固定S011目标为净收益严格>{pct(0.9158029150000013)}且回撤严格<{pct(0.07248663749114126)}。C6105收益余量{(commonr['net_return'] - 0.9158029150000013) * 100:.4f}个百分点，回撤余量{(0.07248663749114126 - commonr['dd']) * 100:.4f}个百分点；全434日年化最低目标25.4081%，并满足原回撤及双频率要求。",
    "",
    "这只是当前开发窗口的中心达标。C6105不是已完成阶段四正式排序的冠军，也未证明与S011具有独立收益机制；仍属于上涨背景中的条件价格修复。",
    "",
    "## 改善来自哪里",
    "",
    "| 对照 | 434收益/回撤 | 415收益/回撤 | 解释 |",
    "|---|---|---|---|",
]
for cid, label in [
    ("C6102", "原均值中心固定3日/100%"),
    ("C6101", "原规则/95%"),
    ("C6105", "固定3日+重新许可/100%"),
    ("C6104", "固定3日+重新许可/95%"),
    ("C6117", "两日失败提前退+重新许可/100%"),
    ("C6108", "单日失败提前退/即时再入/100%"),
]:
    x = rows[cid]["row"]
    a = x["runs"]["full"]
    b = x["runs"]["s011_common"]
    lines.append(
        f"| {cid} {label} | {pct(a['net_return'])}/{pct(a['dd'])} | {pct(b['net_return'])}/{pct(b['dd'])} | {'联合中心通过' if x['both_center_pass'] else '未联合通过'} |"
    )
lines += [
    "",
    "1. 恒定减仓能够过线，但没有提高亏损识别：C5806与C5807的目标、成交日期/方向/价格完全一致，都是21次入场日亏损、其中12次最终盈利。95%投入使入场亏损金额少2499.76元，也使入场正利润少6244.37元；这是实际不同投入账户比较，不是删交易收益。",
    "2. EX059看似“失效确认”的优势包含再入场等待。C5902确认期等于3日持有上限，实际0次提前退出；其完整信号等于固定3日加正步再许可。EX061正交实验确认改善主要来自重新许可，单日失败早退反而受损，两日失败早退也未优于固定退出。",
    "3. 等待的代价真实存在：既有同入场日周期会改变资金规模，若跳过信号，后续入场日期也会变化。需要同时看避开的亏损、错过的盈利和新增/改期机会；不能从基准账本扣掉某个亏损周期推导新收益。具体金额和路径见EX059机制复核及EX061/others/mechanism_report.json。",
    "",
    "C6105与即时全仓C6102有47个共同实际入场日，均同日退出；原队列另有8个周期，新队列另有3个。缺席原日期的8周期中，6个盈利周期在原账户合计赚15555.20元，2个亏损周期合计亏15033.88元；新队列3周期实际赚7874.42元。共同周期的投入资金也已改变，这些分项不能相减来替代账户整体差异。",
    "",
    "## 反证、适用范围与选择代价",
    "",
    "- 三日尺度较敏感：改变观察期为2/4/5/7/10，或持有为2/4/7/10/14，未在本轮形成同样的完整目标优势。中位和日高低中点定义也未联合达标。不能据几个投入点过线声称整个参数区域稳健。",
    "- 即时再入场的固定3日规则在已测93/94/95/96/97%投入过线，92%收益失败、98%回撤失败；97%回撤余量很小。加入重新许可后，已测92.5/93/95/97.5/100%均过线，90%收益不足；只描述已测离散点，不证明连续区间全部有效。",
    "- 将早退设得更激进没有改进，锚失效、修复封顶及条件延持也未提供更优解。观察期/持有期/锚宽的必要扩边已经完成；repair_cap5/7/10及extend上限5/7/10呈现相同路径，不把无效边界继续枚举成新信息。",
    "- C6105相比即时全仓C6102的平均每日净对数收益增量约0.273个基点；配对10日块重采样95%区间约[-2.720,3.904]基点，20日块亦列入原件。区间包含0，增量不能宣称统计确定。该诊断未修正全部历史选择、不证明平稳性，也不是总收益/回撤置信区间。",
    "- 最强时间反证：C6105的2025收益45.26%低于即时对照54.36%，2026收益41.34%高于31.45%；全期实际仅多赚2417.53元。按起始日固定21交易日步长的9个252日继承窗口全部跑输即时对照，最后一个网格窗截至2026-09-23，并不包含末期关键差异，不能泛称所有一年窗口都落后。单独补列期末252日（2025-09-30至2026-10-21），C6105收益77.16%反超对照70.51%。累计财富曾连续295交易日落后，末期反超与避开9月原队列大亏关联，不能宣称普遍提升。",
    "- C6105仍有16次入场日亏损，合计约27479元，其中9次最终转盈、贡献约20995元；前5个盈利周期占正利润44.99%。它没有实现准确识别所有入场亏损，收益集中性和时间依赖需在阶段四正面检验。",
    "- 434/415窗口高度重叠且已被多轮观察；阶段切换不清零此前S015历史选择。日范围成交无量约束、历史17:30可得性未认证；数据和执行限制未改变。",
    "",
    "## 已完成和未完成的验收",
    "",
    "| 项目 | 状态 |",
    "|---|---|",
    "| 434日默认收益、回撤、双频率；415日S011双优 | 16个配置身份同时通过，全部交接 |",
    "| 正式账户、固定对照、因果前缀、资金账本和实现身份 | 当前证据核验；交付发布时逐项认证 |",
    "| 32个合理联合扰动、费用翻倍、正式自检/排序 | 本阶段未执行；不可用阶段二别的身份压力结果替代 |",
    "| 用户选型、技术检验、冻结、PTE/生产 | 未执行，须分别授权 |",
    "",
    "现有实现中的部分参数不影响特定策略：固定退出时confirmation/failure_buffer/max_hold无决策作用，center_below不使用concentration阈值；start为固定研究范围，不得作为调参维度。确认期>=持有上限的失效条件也不会提前退出。阶段四不得通过扰动这些无效参数制造32点通过；需事前解释真实有效参数的适用设计，并把±1日离散尺度敏感性作为明确诊断，不能用小幅资金扰动掩盖它。",
    "",
    "## 交付与下一步",
    "",
    f"本交付保留全部{len(passing)}个联合达标身份、全局四目标非支配前沿及必要机制对照，共{len(selected)}个登记候选；handoff仅含16个本轮达标身份。不同源码或参数身份可能具有相同经济路径，16身份对应{len(pathgroups)}组本轮配对净值指纹，不是16个独立收益来源。旧117个身份及其历史证据不恢复资格。",
    "",
    "建议批准阶段四，对本轮全部中心达标候选开展已约定自检和比较；以C6105解释主要机制，C6104及即时减仓家族保留资金风险取舍，两日早退族保留竞争对照。若真实有效参数的扰动或费用压力不通过，按失败来源决定是否退回阶段二，不继续盲目调整小数阈值。",
    "五轮已回答最重要的机制与边界问题，未启用研究员自定六轮上限的最后一轮，也未把此前阶段二剩余13轮自动转用。尚无独立验证或完整合格结论；下一阶段须用户批准。",
    "",
    "全量概览刷新本轮两次读取未取得结果，随后中止并留证；引用的历史概览不是当前资格证明。当前分支、阶段二交付、每个所用账户、登记候选与本交付分别核验。没有修改平台或研究指南，没有合并master、推送、tag、生产操作。",
    "",
    "五轮实验及完整格点记录位于research/S015/experiments/EX058_20261024至EX062_20261024；EX062/others/stage3_summary.json给出全部达标与前沿身份，stage3_grid.csv保留126个配置。正式assets数据、证据、候选和交付资产须独立保留，仅克隆Git不足以恢复。",
]
report_path = ROOT / "research/S015/materials/stage3_closeout_20261024.md"
report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

# Publisher is already colocated; preserve its reviewed bytes.
manifest = {
    "schema_version": 1,
    "reviewed_for_publication": False,
    "references": {},
    "result_sources": [],
    "materials": [],
    "reports": [],
    "candidates": [],
    "conclusion": "阶段三五轮完成；16个中心联合达标配置全部交接，主要机制为上涨中心折让加退出后重新许可。三日尺度敏感且新增收益统计不确定；阶段四未运行，尚无完整合格策略。",
    "delivery": {
        "revision": 6,
        "report": frozen(report_path),
        "status": "COMPLETE",
        "incomplete_items": [],
        "evidence": [],
    },
}
for n, result in results.items():
    home = BASE / f"EX{n:03d}_20261024"
    alias = f"ex{n:03d}_results"
    manifest["result_sources"].append(
        {
            "experiment_id": home.name,
            "results": frozen(home / "others/results.json"),
            "protocol_refs": frozen(home / "others/protocol_refs.json"),
            "source_root": (home / "src/strategy_runtime").relative_to(ROOT).as_posix(),
            "dependencies": [],
            "results_alias": alias,
            "search": {
                "search_id": f"S015_stage3_EX{n:03d}_20261024",
                "method": "Optuna预定配置排队、四目标结果回填、TDR公共完整账户，4进程单线程seed13",
                "scope": "434/415原窗口各独立10万元空仓，标准每侧0.1%，固定成交合同；不含阶段四",
                "selection": "全部中心经济与频率联合达标、四目标非支配前沿及明确的机制对照",
                "limitations": [
                    "多轮已见开发池及重叠窗口，继承历史选择；重复经济路径不代表独立收益来源。",
                    "配置按content身份计数，源码差异及非影响参数可能产生不同内容身份；技术重复单列。",
                ],
            },
        }
    )
    aliases = [alias] + [f"account:{home.name}:{r['candidate_id']}" for r in result["rows"]]
    paths = list((home / "src").rglob("*.py")) + list((home / "protocols").glob("*.json"))
    paths += [
        p
        for p in (home / "others").glob("*.json")
        if p.name
        not in (
            "results.json",
            "progress.json",
            "final_manifest.json",
            "publication_receipt.json",
            "publication_precheck.json",
            "publication_review.json",
            "closeout_checks.json",
        )
        and not p.name.endswith("_payload.json")
    ]
    paths += list((home / "others").glob("stage3_*.csv"))
    for i, path in enumerate(sorted(paths)):
        name = f"ex{n:03d}_material_{i:03d}"
        manifest["materials"].append(
            {"alias": name, "experiment_id": home.name, **frozen(path), "name": f"{path.stem}-{i}"}
        )
        aliases.append(name)
    if result.get("serial_ref"):
        name = f"ex{n:03d}_serial"
        manifest["references"][name] = {"ref": result["serial_ref"]}
        aliases.append(name)
    manifest["reports"].append(
        {
            "experiment_id": home.name,
            "sha256": digest(home / "report.md"),
            "outcome": "COMPLETED",
            "evidence": aliases,
            "previous": None,
        }
    )
    manifest["delivery"]["evidence"] += aliases
for cid in sorted(selected):
    item = rows[cid]
    home = BASE / item["experiment"]
    row = item["row"]
    manifest["candidates"].append(
        {
            "candidate_id": cid,
            "payload": frozen(home / f"others/{cid}_payload.json"),
            "hypothesis": "上涨价格中心中的暂时折让，经固定或失效退出及明确再许可状态形成完整现金周期策略；以同协议对照解释作用。",
            "judgment": "通过434经济与频率和415固定S011双门，交接阶段四；尚未完整自检，非冻结资格。"
            if cid in passing
            else "中心联合未通过；保留收益回撤前沿或必要机制对照，不进入达标handoff。",
            "handoff": cid in passing,
            "support": [],
            "retention_reason": "全部达标/四目标前沿；附加基线、单日和两日即时退出、中心定义竞争对照服务机制归因。",
        }
    )
save(LAST / "others/final_manifest.json", manifest)
print(summary)
