"""Freeze root's prospective fixed study; source/metadata only, no observations."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-vol-concentration"


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


p71 = read(ROOT / "research/S013/experiments/EX071_20261011/protocols/plan.json")
p76 = read(ROOT / "research/S013/experiments/EX076_20261011/protocols/plan.json")
sources = sorted(WORK.glob("*.py")) + [
    ROOT / ".tmp/s013_vol_research.py",
    ROOT / "research/S013/experiments/EX071_20261011/src/continuation_core.py",
    ROOT / "research/S013/experiments/EX058_20261011/src/common.py",
]
focused = read(WORK / "focused_checks.json")
if focused["status"] != "PASS":
    raise ValueError("Reviewed synthetic checks required")
for name, expected in focused["source_sha256"].items():
    if digest(WORK / name) != expected:
        raise ValueError("Focused proof source drift")
for name, expected in focused["dependencies"].items():
    if digest(ROOT / name) != expected:
        raise ValueError("Focused proof dependency drift")
plan = {
    "status": "PROSPECTIVE_DECLARED",
    "role": "RSCH",
    "stage": 2,
    "frozen_utc": datetime.now(timezone.utc).isoformat(),
    "authorization": "用户明确授权重设研究目标并自主研究；原S013数据及执行合同内",
    "objective": "寻找扣费后仍有盈利余量的做多机会及可交易风险信息，最终保持原四门并改善32点CAGR_Q10/DD_Q90；此项只检验信息，不证明策略目标",
    "original_four_hard_gates_changed": False,
    "new_hard_gates": False,
    "selection_history": "已见截至EX077原开发池证据；EX077整策略未达收益/频率门并停止，本组件不是其退出改装或救援。此前EX071风险方向跨年冲突，EX073风险线索的EX074交易化恶化Q10/Q90；已见选择偏差未被区间校正。",
    "hypothesis": "4日波动在20日中集中可能辨明持仓近期不稳定；原Close的不同时间分布表达，不是新数据。预定观察下行风险正向，继续收益负向。高波动也可能放大反弹是最强反证。",
    "component": "std(logCloseReturn last4, population ddof0)/std(logCloseReturn last20, population ddof0); fixed4/20; zero denominator/unavailable explicitly NaN, no fill/epsilon",
    "scope": "唯一actual_signal_continue:原C8880账本T收盘实际quantity>0，且T当前signal_date决策target1。不能以T+1实际成交、未来退出或标签选池。原1635全T轴后mask。",
    "controls": "原EX07122控制，恢复late_recovery并加入20日log-return population std本身(log_sigma20)，共24；保留原simple-return volatility20，不因共线性按结果删项",
    "labels": {
        "return_4": "Open[T+5]/Open[T+1]-1；相同两端SELL费用抵消；无新BUY费用。原持仓假想延长，不是原真实交易收益",
        "downside_4": "max(0,1-min(O/C T+1..T+4,final O T+5)/O[T+1])；不含已无法逃避的Tclose到nextOPEN变化；不是账户最大回撤",
    },
    "prior_direction": {"return_4": "negative", "downside_4": "positive"},
    "method": read(WORK / "method.json"),
    "interpretation": "全组/年度/原5相位及成熟年份伪样本外与24控制/训练均值两基准完整报告；区间跨零、不稳定或样本外无新增用途会削弱该固定用途。仅风险预测不能证明扣费退出改善，不能自动进入账户。研究诊断不增经济硬门。",
    "stopping": "本项只有1组件1scope两个h4标签的一次统计。无4/20窗口优化、翻符号、挑年份/相位、退出阈值或账户自动救援。若固定用途无依据则止步，不追加同族账户。",
    "price_and_execution": "510500.SH原开发2020-01-02..2026-09-30及原2019 warmup；HFQ原anchor2019-12-31/.2803；无分红叠加；原1%LimitBuyHold合同/1m/lot100/.001费用保持；0新账户",
    "input_references": {
        "old_features": p71["input_references"]["features.csv"],
        "warm_prices": p76["input_references"]["warm69_prices"],
        "native": p71["native_ref"],
    },
    "source_files": {p.relative_to(ROOT).as_posix(): digest(p) for p in sources},
    "native_cache": {
        ".tmp/s013-mechanism-EX058/N0.pkl.gz": "ceded25c20adb4e698ec4dfecd677d26db62c342f339d83be3c0b592a451d26c"
    },
    "predecessors": p76["predecessors"],
    "resources": {
        "workers": 1,
        "blas_threads": 1,
        "component": 1,
        "scope": 1,
        "labels": 2,
        "statistics_calls": 1,
        "new_accounts": 0,
        "providers": 0,
    },
    "limitations": [
        "已见同一开发池，chronological伪样本外并非封存验证",
        "固定原策略持仓池有内生选择，不代表任何新策略的持仓池",
        "反事实固定4日延长可能跨过旧策略未来退出，不是已实际发生的账户盈亏",
        "日Open/Close风险忽略盘中极值；4日std估计噪声大",
        "若风险信息存在，仍需独立可执行退出实验确认反弹机会成本/费用/交易次数/32点表现",
    ],
}
with (WORK / "prospective.json").open("x", encoding="utf-8") as stream:
    json.dump(plan, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.write("\n")
print({"status": "FROZEN", "source_n": len(sources), "new_accounts": 0})
