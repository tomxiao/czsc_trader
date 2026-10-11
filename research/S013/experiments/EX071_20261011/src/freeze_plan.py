"""Freeze final formatted source and prospective protocol; no actual data/statistics."""

from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
import json
import continuation_core as core
import opportunity_statistics as stats

HERE = Path(__file__).parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").exists())


def read(path):
    return json.loads(path.read_text("utf-8-sig"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    sources = {p.name: digest(p) for p in sorted(HERE.glob("*.py"))}
    focused = read(HERE / "focused_checks.json")
    assert focused["status"] == "PASS" and focused["source_hashes"] == sources
    old69 = read(
        ROOT / "research/S013/experiments/EX069_20261011/protocols/verification_references.json"
    )
    old66 = read(
        ROOT / "research/S013/experiments/EX066_20261011/protocols/final_evidence_references.json"
    )
    # Read only exact public N0 identity used by frozen EX069 protocol.
    native = read(ROOT / "research/S013/experiments/EX069_20261011/protocols/plan.json")[
        "native_ref"
    ]
    plan = {
        "role": "RSCH",
        "stage": 2,
        "prospective_frozen_utc": datetime.now(timezone.utc).isoformat(),
        "authorization": "用户授权自主研究；root已认可源码/四scope并授权完成前瞻冻结后执行EX071固定统计与独立核验",
        "economic_targets_unchanged": True,
        "new_hard_gates": False,
        "new_accounts": 0,
        "question": "EX066/067的late_weakness持有池线索是否在真实成交持仓与已知持仓年龄/盈亏控制后仍有继续持有信息，尤其2023？",
        "selection_history": "已见EX066/067/068/069/070开发池结论；复用已发现的单一固定组件，结果为条件线索确认而非封存验证，置信区间未纠正研究选择偏差",
        "feature_method": core.METHOD,
        "statistics": stats.METHOD,
        "hypothesis_signs": {
            "late_weakness": "positive return4, negative downside4; h8 auxiliary same direction; never reverse on result"
        },
        "primary": ["return_4", "downside_4"],
        "auxiliary": ["return_8", "downside_8"],
        "controls": list(stats.CONTROLS),
        "control_exclusion": "原20去late_recovery，因其是组件的精确线性反向；按代数预先排除，不按表现挑选；其余19固定控制加holding_age/entry_mark_pnl/known_falling，共22",
        "fixed_scopes": [
            "actual_held",
            "declining_actual_held",
            "actual_signal_continue",
            "actual_signal_exit",
        ],
        "scope_definition": "T account_daily.date收盘 quantity>0；declining用T momentum20<0；continue/exit用T signal_date当前target1/0（已知下一日计划，不是未来实际成交）；before状态分歧仅审计计数；T+1成交成功不能选样本",
        "accounting_companions": "marked_close_net/risk_close/increment/immediate只作逐行账目解释，不追加IC/拟合；两端相同SELL费用取消，绝不扣新BUY费",
        "partial_df": "n-rank(intercept+rankcontrols)>=10且n>=20；否则null及reason/rank/df；常数known_falling/同池约束按实际rank计算；不放低DF或合并薄scope",
        "price_and_time": "EX058 C8880 authenticatednative cache/public full evidence exact equality；仅native固定HFQ execution_daily OPEN/CLOSE（2019-12-31..2026-09-30），原1635 T信号网格；原warmup控制已在EX069features；0新增fetch/provider",
        "input_references": {
            "features.csv": old69["features.csv"],
            "old_labels.csv": old66["labels.csv"],
            "predecessor_verification.json": old69["verification.json"],
        },
        "native_ref": native,
        "source_files": sources,
        "common_sha256": digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py"),
        "independent_check": "真实fill逐T含T当天重建数量/成本/age/PnL，date而非prior signal_date；信号intent逐T；每行h4/h8收益与EX066仿射恒等式，close liquidation-immediate=increment；独立OPEN/CLOSE风险/maturity；各scope/year/phase rank/DF、成熟共同模型样本、truth/modelMSE/训练均值baselineMSE",
        "resource_budget": {
            "workers": 1,
            "blas_threads": 1,
            "components": 1,
            "scopes": 4,
            "labels": 4,
            "fixed_models": 2,
            "max_yearly_fits": 192,
            "bootstrap_replicates": 500,
            "block_sessions": 40,
            "seed": 13,
            "ridge_alpha": 10,
            "market_provider_requests": 0,
            "new_accounts": 0,
            "parameter_trials": 0,
        },
        "stop": "固定结果薄/反向/无增量则保留并停止；无窗口/期限/方向/阈值救援，无持有管理实现、无账户、无经济达标宣称；parent作最终科学裁决与交付",
        "limitations": [
            "继续持有价格标签与旧新买标签为仿射同信息，不能把费用重表达当新证据",
            "old actualholding和currenttarget由原策略内生，scope不是独立随机试验",
            "日OPEN/CLOSE观察风险非路径/账户最大回撤且忽略盘中极值",
            "固定T数量反事实持有穿过原退出，不是旧账户实现收益",
            "2022/23年、各相位与已知退出小池会薄，null如实保留",
            "过往阶段三定时延迟/普通gapexit已有失败，不重复，不直接据相关性改退出规则",
        ],
    }
    for name, value in (
        (
            "method.json",
            {"component": core.METHOD, "statistics": stats.METHOD, "source_files": sources},
        ),
        ("prospective_plan.json", plan),
    ):
        path = HERE / name
        assert not path.exists(), "No overwrite frozen protocol"
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
        )
    print(
        {
            "source_only_frozen": True,
            "sources": len(sources),
            "market_reads": 0,
            "allocations": 0,
            "statistics_runs": 0,
        }
    )


if __name__ == "__main__":
    main()
