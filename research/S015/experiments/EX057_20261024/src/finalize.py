from pathlib import Path
from hashlib import sha256
import json
import re

ROOT = Path.cwd()
BASE = ROOT / "research/S015/experiments"


def read(p):
    return json.loads(p.read_bytes())


def dump(p, v):
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def home(n):
    return BASE / f"EX{n:03d}_20261024"


results = {n: read(home(n) / "others/results.json") for n in range(52, 58)}
rows = {r["candidate_id"]: r for v in results.values() for r in v["rows"]}
old = read(home(49) / "others/results.json")
rows.update({r["candidate_id"]: r for r in old["rows"]})
manifest = {
    "reviewed_for_publication": False,
    "references": {},
    "materials": [],
    "reports": [],
    "components": [],
    "prototypes": [],
    "comparisons": [],
}
refs = manifest["references"]
mats = manifest["materials"]
aliases = {}
exrefs = {n: [] for n in range(51, 58)}


def material(n, p, key):
    assert key not in refs and all(x["alias"] != key for x in mats)
    mats.append(
        {
            "alias": key,
            "experiment_id": home(n).name,
            "path": p.relative_to(ROOT).as_posix(),
            "sha256": sha256(p.read_bytes()).hexdigest(),
        }
    )
    aliases[p] = key
    exrefs[n].append(key)
    return key


for n in range(51, 58):
    files = list((home(n) / "src").rglob("*.py")) + list((home(n) / "protocols").glob("*.json"))
    if n == 51:
        files.append(ROOT / "research/S015/materials/price_process_stage2_20261024.md")
    files += [
        p
        for p in (home(n) / "others").glob("*.json")
        if p.name
        not in (
            "progress.json",
            "final_manifest.json",
            "publication_receipt.json",
            "integrated_delivery.json",
        )
    ]
    files += [
        p
        for p in (home(n) / "others").glob("*.csv")
        if not re.match(r"C\d+_(full|s011_common)_", p.name)
    ]
    for i, p in enumerate(sorted(set(files))):
        material(n, p, f"ex{n}_m{i}")
    if n >= 52:
        for r in results[n]["rows"]:
            key = r["candidate_id"]
            refs[key] = {"ref": r["evidence"]}
            exrefs[n].append(key)
    if n in (52, 57):
        key = f"serial{n}"
        refs[key] = {"ref": results[n]["serial_ref"]}
        exrefs[n].append(key)
    report = home(n) / "report.md"
    assert "Status: COMPLETED" in report.read_text(encoding="utf-8")
    manifest["reports"].append(
        {
            "experiment_id": home(n).name,
            "sha256": sha256(report.read_bytes()).hexdigest(),
            "outcome": "COMPLETED",
            "evidence": exrefs[n],
        }
    )


def alias(n, rel):
    return aliases[home(n) / rel]


def protocol(n):
    return alias(n, "protocols/process.json" if n == 51 else "protocols/accounts.json")


def result(n):
    return alias(n, "others/results.json")


def runtime(n):
    return alias(
        n, "src/price_process.py" if n == 51 else "src/strategy_runtime/strategies/price_process.py"
    )


initial = read(home(51) / "protocols/process.json")
for k, v in {
    **initial["sources"],
    "loader": initial["loader"],
    "events": initial["events"],
}.items():
    refs["input_" + k] = {"ref": v}
refs["summary_source"] = {"ref": results[52]["summary_source"]}
for c in ("C4900", "C4903", "C4904"):
    refs[c] = {"ref": rows[c]["evidence"]}
oldrefs = read(home(49) / "others/published_refs.json")["materials"]
old_alias = []
for i, (k, v) in enumerate(oldrefs.items()):
    key = f"old_m{i}"
    refs[key] = {"ref": v}
    old_alias.append(key)
    if k == "src/strategy_runtime/strategies/price_information.py":
        old_runtime = key
    if k == "protocols/accounts.json":
        old_protocol = key
refs["old_report"] = {"ref": read(home(49) / "others/published_refs.json")["report"]}


def component(cid, role, judgment, n, control, status="SUPPORTED", entry="permission"):
    manifest["components"].append(
        {
            "component_id": cid,
            "definition": {
                "evidence": runtime(n),
                "entrypoint": f"strategy_runtime.strategies.price_process.{entry}",
            },
            "role": role,
            "label": "完整原型账户及机会层必要对照",
            "horizon": "T+1入场；三信号日持有或明确价格状态退出",
            "control": control,
            "availability": "约定T17:30，正式回放默认20:31；C5506/C5404代表计划双时钟等价。完整日线/8根30分钟线绑定，历史发布/修订可得性仍受现有合同限制。",
            "price_basis": "复权价格用于状态；未复权价格执行，HFQ_RESEARCH / DAILY_RANGE_V3",
            "applicability": "159326.SZ、原434/415已见开发池、只多无杠杆、周期锁定资金及每侧0.1%费用",
            "judgment": judgment,
            "tests": [
                {
                    "test_id": cid + "_test",
                    "experiment_id": home(n).name,
                    "protocol": protocol(n),
                    "status": status,
                    "explanation": judgment,
                    "evidence": [result(n)],
                }
            ],
        }
    )


component(
    "migration",
    "入场背景：价格中心跨三日抬高",
    "均值组合102.90%/7.46%，删除上移背景仅43.15%/27.24%；下移背景亏9.07%。中位定义也得到相同方向的必要对照。支持此组合内的背景用途，不等于参与者因果。",
    56,
    "C5506 vs C5601/C5602",
)
component(
    "discount",
    "入场触发：收盘低于当日价格中心",
    "均值组合优于中心单独41.14%/12.80%；中心上移却收盘在中心上方亏18.09%。折让与背景需协作；信号日上涨也有正向事件，未以绝对下跌或超卖为必要条件。",
    56,
    "C5506 vs C5600/C5603",
)
component(
    "fixed3",
    "持有及退出：三信号日后释放资金",
    "基础可执行容器。与价格修复退出存在盈利/风险取舍；不声称三日普遍最优，也未以期限网格寻找达标。",
    54,
    "C5303 vs C5404/C5405",
    "NOT_APPLICABLE",
    "intentions",
)
component(
    "repair",
    "退出：收盘回到价格中心或以上",
    "在中位定义中回撤9.90%降至8.13%，收益88.83%降至84.34%；均值定义下不优于固定退出，支持有条件风险取舍，不是整体双优。",
    54,
    "C5404 vs C5303",
    entry="intentions",
)
component(
    "reversal",
    "退出保护：跨日中心反转也退出",
    "中位修复原型加反转退出，回撤8.13%降至6.30%，收益84.34%降至60.54%；后续净损益显著降低，并在部分反弹前止损。",
    54,
    "C5405 vs C5404",
    entry="intentions",
)
component(
    "distributed",
    "入场加严：要求上涨分散、收盘强",
    "C5203全周期亏8.30%，弱于中心简单入口；首事件均值为负。停止把分散程度作为高质量入场保证。",
    52,
    "C5203 vs C5202/C5201",
    "INEFFECTIVE",
)
component(
    "first",
    "入场状态切换：中心从非正转正",
    "中位首次转正固定三日38.63%/7.70%优于center36.50%/12.81%，但叠加折让后频率不足，均值版本32.67%/10.29%。仅保留受限线索，不继续叠加。",
    53,
    "C5300 vs C5202; EX054/056反证",
)
component(
    "execution",
    "完整执行：限价、费用、锁定周期预算",
    "必要执行规则，无独立超额收益主张；所有106正式账户独立账本核验，代表串并行一致及双倍费用核验。",
    57,
    "标准成本与压力成本合同",
    "NOT_APPLICABLE",
    "PriceProcess",
)
manifest["components"][-1]["definition"]["evidence"] = runtime(52)
manifest["components"][-1]["applicability"] = (
    "标准每侧0.1%，明确压力场景每侧0.2%；资金预算必须与执行费用一致。"
)
manifest["components"].append(
    {
        "component_id": "legacy_model",
        "definition": {
            "evidence": old_runtime,
            "entrypoint": "strategy_runtime.strategies.price_information.PriceInformation",
        },
        "role": "旧U/BP/BPF原型定义和模型对照",
        "label": "既有固定三日账户",
        "horizon": "固定三信号日；模型滚动发布",
        "control": "EX049 U/BP/BPF",
        "availability": "旧训练发布及运行时审计；BPF份额历史发布时间和修订限制保留",
        "price_basis": "同一标准执行及新周期资金合同",
        "applicability": "2025-02-27模型可用后；此前空仓",
        "judgment": "BP有相对U用途但风险过大；BPF事件增益没有转化为BP之上的账户增益。作为完整历史对照，不恢复资格。",
        "tests": [
            {
                "test_id": "legacy_account_control",
                "experiment_id": "EX049_20261024",
                "protocol": old_protocol,
                "status": "SUPPORTED",
                "explanation": "BP53.93%/33.10% vs U24.34%/30.43%；BPF29.87%/28.23%，不同目标有取舍。",
                "evidence": ["C4900", "C4903", "C4904"],
            }
        ],
    }
)
limits = [
    "全部数据反复用于开发和选择；没有新独立验证；两评价窗高度重叠。",
    "组件删项与退出改变交易队列和本金，账户差异不是市场因果归因。",
    "官方signal_cash_fraction归因为UNSUPPORTED；独立账本核验及描述已通过，不冒称官方支持。",
    "现有数据的历史发布/修订与日线执行现实差异沿用原合同；本轮不使用分钟成交量。",
    "32点联合扰动及阶段四未完成；当前无合格候选，DEVELOP不代表阶段批准。",
]
specs = [
    (
        "P_MEAN_FIXED",
        "C5506",
        ["migration", "discount", "fixed3", "execution"],
        "DEVELOP",
        "主原型：跨日价格中心上移时，临近收盘相对折让可能提供尚未完成的修复机会；用短持有窗口承接。",
        "已有删项、替代定义和双倍费用证据；全周期102.90%/7.46%，415收益过线但回撤超上限0.2103个百分点。",
        "若获阶段三批准，先分离资金使用强度与持有失效规则的完整对照，保持标准原型不变；改善若仅靠损失过多盈利或脆弱单点则回退。",
    ),
    (
        "P_MEDIAN_FIXED",
        "C5303",
        ["migration", "discount", "fixed3", "execution"],
        "DEVELOP",
        "相同背景与折让机制，以日内中位数表达价格中心。",
        "88.83%/9.90%，双目标未达；作为机制代表与均值替代对照，避免只留下最高结果。",
        "阶段三固定保留参照，检验均值优势是否来自可解释队列变化。",
    ),
    (
        "P_MEDIAN_REPAIR",
        "C5404",
        ["migration", "discount", "repair", "execution"],
        "INVESTIGATE",
        "价格折让修复后释放资金。",
        "84.34%/8.13%，比固定规则略少收益和更低回撤；最大9月亏损并非一概更早退出而改善。",
        "作为退出竞争对照；不直接替换主原型。",
    ),
    (
        "P_MEDIAN_RISK",
        "C5405",
        ["migration", "discount", "repair", "reversal", "execution"],
        "INVESTIGATE",
        "修复完成或上移背景失效即退出。",
        "60.54%/6.30%，回撤低于S011上限但收益不足；不能把它的低回撤与另一原型收益拼接。",
        "用于区分真实失效与短暂回落的风险对照；保留其盈利牺牲反证。",
    ),
    (
        "P_DAILY_MID",
        "C5509",
        ["migration", "discount", "fixed3", "execution"],
        "INVESTIGATE",
        "以日高低几何中点表达相同条件性价格折让。",
        "92.28%/9.51%；说明盘中独有信息并非已证实的必要来源。",
        "保留廉价信息替代对照；不得宣传均值中心独立于日线信息。",
    ),
    (
        "P_CENTER_MEAN",
        "C5600",
        ["migration", "fixed3", "execution"],
        "STOP",
        "只要求均值价格中心上移。",
        "41.14%/12.80%，收益和回撤均弱于完整组合。",
        "停止作为独立主线，保留删项对照。",
    ),
    (
        "P_BELOW_MEAN",
        "C5601",
        ["discount", "fixed3", "execution"],
        "STOP",
        "无上移背景的普遍收盘折让修复。",
        "43.15%/27.24%，删除背景后风险显著扩大。",
        "保留背景必要性对照，不以普遍折让取代完整原型。",
    ),
    (
        "P_FALLING",
        "C5602",
        ["discount", "fixed3", "execution"],
        "STOP",
        "下移中心背景中的折让反弹。",
        "−9.07%/25.47%，此定义不支持下移背景的反弹用途。",
        "停止该定义，不外推否定全部超跌机制。",
    ),
    (
        "P_ABOVE",
        "C5603",
        ["migration", "fixed3", "execution"],
        "STOP",
        "在上移背景追随强收盘。",
        "−18.09%/23.43%，与折让方向相反。",
        "停止强收盘条件作为此次原型的入口。",
    ),
    (
        "P_CENTER_MEDIAN",
        "C5202",
        ["migration", "fixed3", "execution"],
        "STOP",
        "只要求中位价格中心上移。",
        "36.50%/12.81%，优于普通收盘动量，弱于背景与折让组合。",
        "保留发现过程对照。",
    ),
    (
        "P_MOMENTUM",
        "C5201",
        ["fixed3", "execution"],
        "STOP",
        "三日收盘上涨后继续上涨。",
        "12.48%/17.49%，不足解释价格中心组合的账户优势。",
        "保留最简单正涨幅基线。",
    ),
    (
        "P_U",
        "C5200",
        ["fixed3", "execution"],
        "STOP",
        "无筛选固定周期持有。",
        "1.22%/31.74%，交易费用和后续亏损显著。",
        "只作共同初始窗口基线。",
    ),
    (
        "P_DISTRIBUTED",
        "C5203",
        ["distributed", "fixed3", "execution"],
        "STOP",
        "分散而强的上涨过程还有延续。",
        "−8.30%/22.74%；事件首日与账户均反证初始预期。",
        "停止该具体定义，不追加邻近阈值。",
    ),
    (
        "P_FIRST",
        "C5300",
        ["migration", "first", "fixed3", "execution"],
        "INVESTIGATE",
        "优先捕捉价格中心首次转正。",
        "38.63%/7.70%，回撤较低但收益远不足，且与折让叠加会丢失频率。",
        "保留状态转折竞争解释，不与主原型机械叠加。",
    ),
    (
        "P_LATE",
        "C5605",
        ["migration", "discount", "fixed3", "execution"],
        "DEVELOP",
        "同均值组合，晚起点仅用于对齐旧模型可用日期。",
        "100.49%/7.46%，在共同起点同时优于旧BP收益和回撤；不替代原窗口目标。",
        "仅作为同起点历史增量证据；主原型仍用完整窗口。",
    ),
    (
        "P_OLD_BP",
        "C4903",
        ["legacy_model", "execution"],
        "INVESTIGATE",
        "旧量价加价格路径模型预测三日收益。",
        "53.93%/33.10%，已无资格；新同起点组合改善收益与回撤。",
        "保留历史参照，当前不扩其模型搜索。",
    ),
    (
        "P_OLD_U",
        "C4900",
        ["legacy_model", "execution"],
        "STOP",
        "模型就绪日起无筛选三日容器。",
        "24.34%/30.43%，与本轮C5209逐路径一致。",
        "只保留旧共同起点控制。",
    ),
    (
        "P_OLD_BPF",
        "C4904",
        ["legacy_model", "execution"],
        "STOP",
        "旧量价、路径与ETF份额信息联合。",
        "29.87%/28.23%，事件增量未保住BP账户收益；份额可得性限制未消失。",
        "停止作为当前优先机制，保留反证。",
    ),
]
for pid, c, components, disposition, hypothesis, judgment, nextstep in specs:
    n = int(c[1:3])
    oldcase = n == 49
    source = old_runtime if oldcase else runtime(n)
    evid = (
        old_alias + ["old_report"]
        if oldcase
        else [
            source,
            alias(n, f"others/{c}_payload.json"),
            protocol(n),
            result(n),
            alias(n, "others/audit.json"),
        ]
    )
    manifest["prototypes"].append(
        {
            "prototype_id": pid,
            "definition": {
                "evidence": source,
                "entrypoint": "strategy_runtime.strategies.price_information.PriceInformation"
                if oldcase
                else "strategy_runtime.strategies.price_process.PriceProcess",
            },
            "hypothesis": hypothesis,
            "components": [
                {
                    "component_id": v,
                    "role": next(
                        x["role"] for x in manifest["components"] if x["component_id"] == v
                    ),
                    "rationale": "按该候选已发布参数启用；具体角色与必要对照见组件条目和原型报告。",
                }
                for v in components
            ],
            "evaluations": [c],
            "disposition": disposition,
            "judgment": judgment,
            "limitations": limits,
            "next_step": nextstep,
            "evidence": evid,
            "missing_evaluation_reason": None,
            "sources": [],
        }
    )
pairs = [
    (
        "P_MEAN_FIXED",
        "P_MEDIAN_FIXED",
        55,
        "中心定义替代",
        "均值领先，但事件平均并未全面领先；盈利差异来自实际交易队列和后续持有，仍有选择偏差。",
    ),
    ("P_MEAN_FIXED", "P_CENTER_MEAN", 56, "删除折让条件", "完整组合同时改善收益和回撤。"),
    ("P_MEAN_FIXED", "P_BELOW_MEAN", 56, "删除上移背景", "背景条件减少风险并提高收益。"),
    (
        "P_MEAN_FIXED",
        "P_FALLING",
        56,
        "反转背景解释",
        "下移背景折让为负，不支持泛化为任意超跌买入。",
    ),
    ("P_MEAN_FIXED", "P_ABOVE", 56, "折让与强收盘竞争", "追强条件亏损，完整组合优势具有方向性。"),
    ("P_MEDIAN_FIXED", "P_CENTER_MEDIAN", 53, "中位定义折让用途", "增益不是只有均值定义才出现。"),
    (
        "P_MEDIAN_REPAIR",
        "P_MEDIAN_FIXED",
        54,
        "折让完成退出",
        "收益略降且风险下降，实际交易说明并非所有亏损提前退出。",
    ),
    ("P_MEDIAN_RISK", "P_MEDIAN_REPAIR", 54, "反转保护", "低回撤以牺牲较多后续盈利换取。"),
    ("P_MEAN_FIXED", "P_DAILY_MID", 55, "是否必须盘中数据", "日线替代也强，不能宣称独有盘中信息。"),
    ("P_CENTER_MEDIAN", "P_MOMENTUM", 52, "普通涨幅控制", "价格中心入口在账户上改善收益与回撤。"),
    (
        "P_DISTRIBUTED",
        "P_CENTER_MEDIAN",
        52,
        "复杂分散条件必要性",
        "加严条件反而亏损，停止初始假设。",
    ),
    (
        "P_FIRST",
        "P_CENTER_MEDIAN",
        53,
        "状态切换与持续许可",
        "首次转正降低回撤，但不能与其他组件优势相加。",
    ),
    (
        "P_LATE",
        "P_OLD_BP",
        56,
        "同起点旧原型比较",
        "新同起点100.49%/7.46% vs BP53.93%/33.10%，双指标改善但仍未过固定S011双门。",
    ),
    ("P_OLD_BP", "P_OLD_U", 49, "旧路径模型整体增量", "收益提高但回撤更大；历史资格不恢复。"),
    (
        "P_OLD_BPF",
        "P_OLD_BP",
        49,
        "事件增量能否成为策略增量",
        "份额联合降低回撤却损失大量收益，不能从事件表现推导原型更优。",
    ),
]
for i, (s, c, n, q, conclusion) in enumerate(pairs):
    manifest["comparisons"].append(
        {
            "comparison_id": f"compare_{i + 1:02d}",
            "subject_id": s,
            "control_id": c,
            "question": q,
            "protocol": old_protocol if n == 49 else protocol(n),
            "evidence": ["C4900", "C4903", "C4904"] if n == 49 else [result(n)],
            "conclusion": conclusion,
        }
    )
manifest["conclusion"] = (
    "阶段二交付完成：发现上移价格中心与收盘相对折让组合的有条件完整账户优势；均值与中位固定原型值得发展。原始分散推进假设被反证，退出保护有真实收益风险取舍。七轮已完成、13轮未用；无合格策略，32点扰动未做。建议用户批准阶段三后再以达标为目标完善资金与持有规则，本轮不自动执行。"
)
report = [
    "# S015 阶段二原型交付：价格中心上移与收盘折让",
    "",
    "Status: COMPLETE",
    "",
    manifest["conclusion"],
    "",
    "## 已交付什么，为什么值得进入下一阶段",
    "",
    "核心成果是可执行原型及组件协作证据。主原型C5506在价格中心跨三日上移、收盘却低于当日中心时入场，以三信号日持有承接短期修复。这里的“中心”是日内8个30分钟收盘对数的均值；它表示价格位置，不代表资金流或真实公允价值。上移背景、相对折让各自都有必要删项对照，单独使用任一条件都明显弱于组合。中位中心也保留相同协作；因此不是只凭最佳点或组件事件均值推荐。",
    "经济解释仍为假设：较高的跨日交易价格状态中，收盘暂时回落后，修复可能继续到T+1实际买入之后。它不要求绝对下跌、超卖或回到原先价格；mean组合91个许可日中28个信号日上涨、65个五日上涨，相关事件也为正。它仍属于条件性短期价格修复家族，不能声称已证明与S011经济来源正交或收益低相关。下移背景折让亏损是有意义的竞争解释反证。",
    "",
    "## 完整原型和目标差距",
    "",
    "| 原型 | 434净收益 | 434年化 | 434最大回撤 | 415净收益 / 最大回撤 | 闭合交易 / 60日中位 | 费用元 |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
]
labels = {
    "C5506": "均值中心＋折让，固定3日",
    "C5303": "中位中心＋折让，固定3日",
    "C5404": "中位中心＋折让，修复退出",
    "C5405": "中位中心＋折让，修复/反转退出",
    "C5509": "日线中心＋折让，固定3日",
    "C5600": "仅均值中心上移",
    "C5601": "仅均值收盘折让",
    "C5602": "下移中心内折让",
    "C5603": "上移中心内强收盘",
    "C5201": "普通三日涨幅",
    "C5200": "无筛选固定3日",
}
for c, label in labels.items():
    f = rows[c]["runs"]["full"]
    v = rows[c]["runs"]["s011_common"]
    report.append(
        f"| {c} {label} | {100 * f['net_return']:.4f}% | {100 * f['cagr']:.4f}% | {100 * f['dd']:.4f}% | {100 * v['net_return']:.4f}% / {100 * v['dd']:.4f}% | {f['closed']} / {f['frequency_median']:.0f} | {f['fees']:.2f} |"
    )
report += [
    "",
    "两个窗口分别10万元空仓起始；434日2025-01-02—2026-10-21，415日2025-02-06—2026-10-21，75日预热保持。S011固定比较线：415净收益严格大于91.58029150000013%，最大回撤严格小于7.248663749114126%，两项必须同时满足。C5506收益超线10.0559个百分点，回撤仍超上限0.2103个百分点，故未过双门，不能四舍五入判合格。",
    "C5506通过434日中心经济与双频率条件：年化50.8065%高于基准16.9387%的1.5倍，回撤7.4606%低于基准36.2900%的0.8倍且低于25%；频率中位8，375/375窗口至少3次。原32个联合扰动和完整资格检验未完成。所有历史117个登记身份保持原状，本轮没有登记、预选或冻结。",
    "共同2025-02-27起点的C5605为100.4862%/7.4618%，旧BP为53.9284%/33.1021%，旧U为24.3383%/30.4342%，旧BPF为29.8730%/28.2268%。该比较支持相对已有原型的完整账户改进，但晚起点不替代原434/415目标。",
    "",
    "## 信号、组件与策略的证据链",
    "",
    "初始假设“上涨分散则更可持续”没有成立：分散推进三日首次事件为负，C5203完整账户亏8.30%。转向来自其反例：简单中心上移更好，而要求强收盘更差。EX053拆解后发现折让交互，EX054与EX056分别在中位和均值定义下验证背景与折让的用途。均值中心单独41.14%/12.80%，折让单独43.15%/27.24%，组合102.90%/7.46%；这些是独立资金账户对照，不是将两个组件收益相加。",
    "固定三日是基础持有容器，不宣传为普遍最优组件。中位修复退出84.34%/8.13%提供较低风险的竞争原型；增加中心反转保护为60.54%/6.30%，显示明确盈利代价。2026-03-03同日入场的固定原型随后盈利，反转退出却提前兑现亏损；不能仅针对9月最大亏损设计规则。均值定义下修复退出也不优于固定退出。",
    "EX055的2/5日尺度、均值/中位及日线高低中点共12个代表变体都盈利，但结果幅度敏感，不能以“均盈利”宣称32点稳健通过。日线中点原型92.28%/9.51%说明盘中独有数据不是已证实必要来源。",
    "",
    "## 入场当天亏损与会错过的盈利",
    "",
    "同一431个就绪机会中，mean组合的入场日标签有89个可观察结果，均值0.6284%；按全部423个可观察入场机会的正负金额分别作分母，组合放弃85.3398%的亏损金额，同时遗漏66.9149%的盈利金额。三日标签对应放弃87.0446%亏损、遗漏72.1237%盈利。每个机会独立10万元、彼此重叠，比例不是准确率，也不是连续账户可以直接节约的现金。",
    "真实C5506账户有21次入场日亏损，合计36260元；其中12次后来盈利。因此它没有解决“辨认并剔除所有入场亏损”的问题。入场日净损益50896元，后续段52002元；相对中位中心，入场净损益略低，后续段增加约14736元。不能将均值账户优势归因于更准确的入场亏损识别。",
    "",
    "## 压力、时间依赖与最强反证",
    "",
    "双倍每侧费用0.2%时，资金锁定数量与买入持有均按实际费用重算。中位固定、修复、均值固定的434净收益分别69.89%、62.24%、81.98%，回撤10.44%、8.85%、8.01%；三个原型均通过本次约定费用压力条件。该证据不代替完整阶段四自检。",
    "C5506年度续接收益2025为54.36%、2026为31.45%；前5盈利周期占全部正利润42.90%。最大回撤发生在2026-05-13到06-08；最大单周期损失在9月24—30日，为12887元。选择均值后回撤仍未过门槛，且主导损失日期不同于中位版本，说明不能围绕一个已知大亏损修补。",
    "全部样本已经反复用于信号、组件、结构和参数选择；没有独立验证，年度与两个重叠窗口也不是独立样本。固定定义相邻替代仍明显改变收益风险，均值最佳是选择后的结果。无法据当前证据证明未来利润或S011低相关。历史发布/修订可得性及日线执行现实限制沿用原合同；本轮未使用存在疑问的分钟成交量。",
    "",
    "## 计算、证据与额度",
    "",
    "已完成EX051—057共7轮，授权20轮剩余13轮未使用。1轮机会诊断，50个标准成本配置形成100个正式窗口账户，3个压力配置形成6个正式账户；另4个串行技术复算，合计110次物理窗口账户计算。技术修正没有新计轮数；新身份不等于新增登记候选，也不等于独立假设。",
    "物理特征截断、意图前缀、原规则不漂移、代表串并行五账本一致均核验；106个正式账户的费用、现金、持仓、周期锁定预算与剩余量、收益频率独立对账通过。公开归因接口返回UNSUPPORTED，保留原状态，未制造替代因果归因。最终交付FULL验证和各实验报告发布验证以回执为准。",
    "正式账户使用运行时默认20:31；约定17:30与20:31在C5506/C5404各434日的认证绑定输入、实际账户前态下，公开SRT全部计划字段除生成时间外一致，868组计划/信号身份匹配正式账户。该项没有模拟成交或新增账户。它不证明历史供应商17:30发布/修订可得，亦非全部候选逐项时钟复验；详见[时钟核验](../../../experiments/EX057_20261024/others/clock_checks.json)。",
    "源码、参数载荷、事前协议、实际账户、机会分析和会计核验均显式关联本PROTOTYPES面板。assets内不可变证据与运行资产必须保留；仅克隆Git不能恢复全部证据。项目指南及平台源码未修改，未操作生产、远端或master。",
    "",
    "| 轮次 | 问题与报告 | 标准配置 / 压力配置 | 正式窗口账户 |",
    "| --- | --- | ---: | ---: |",
]
titles = {
    51: "过程分散与集中",
    52: "最小完整原型",
    53: "中心状态拆解",
    54: "背景与折让协作及退出",
    55: "尺度与中心定义反证",
    56: "均值删项与机会代价",
    57: "双倍费用压力",
}
for n in range(51, 58):
    report.append(
        f"| {n - 50} | [EX{n:03d} {titles[n]}](../../../experiments/EX{n:03d}_20261024/report.md) | {'0 / 0' if n == 51 else str(len(results[n]['rows'])) + ' / 0' if n < 57 else '0 / 3'} | {0 if n == 51 else results[n]['formal_accounts']} |"
    )
report += [
    "",
    "## 下一步建议与停止条件",
    "",
    "建议批准进入阶段三，以C5506为主要承接原型，保留C5303的中位定义、C5404的退出竞争方案以及必要删项基线。依据是完整账户优势、两个关键条件在两种定义下的协作、频率兼容和费用压力存活；不是因为回撤只差一点或仍有预算。",
    "首项问题应分开比较资金使用强度与持有失败规则：资金调整能否用已有收益余量换取足够风险下降，退出调整能否区分持续失效与暂时回落，而不重复牺牲恢复段利润。每项与既有原型固定比较，不同时调多个部件再只报最好值。后续完整资格检验须覆盖原联合扰动等全部条件。",
    "若改进仅来自个别日期、细窄定义或少数盈利周期，若合理代表尺度下的组件协作消失，或风险改善持续依赖过大的收益牺牲，应回退阶段二重新检查机制；不能靠移动窗口、降低目标或拼接不同账户优势过线。",
    "当前停止继续试点是因为阶段二已经形成可承接的有依据原型；进一步以过线为目的寻找配置属于阶段三，须取得用户批准。本轮不自动消耗剩余13轮进入优化，也不承诺阶段三必然产生合格策略。",
]
report_path = ROOT / ".tmp/s015_delivery_report.md"
report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
manifest["delivery"] = {
    "revision": 1,
    "predecessors": [],
    "status": "COMPLETE",
    "incomplete_items": [],
    "report_path": report_path.relative_to(ROOT).as_posix(),
    "report_sha256": sha256(report_path.read_bytes()).hexdigest(),
    "evidence": list(refs) + [m["alias"] for m in mats],
}
dump(ROOT / ".tmp/s015_final_manifest.json", manifest)
print(
    {
        "rounds": 7,
        "standard_configurations": sum(len(results[n]["rows"]) for n in range(52, 57)),
        "formal_accounts": sum(v["formal_accounts"] for v in results.values()),
        "technical_accounts": sum(v["technical_accounts"] for v in results.values()),
        "prototypes": len(manifest["prototypes"]),
        "materials": len(mats),
    }
)
