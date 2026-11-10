"""Record approved joint-search design before any account evaluation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENTS = ROOT / "research/S019/experiments"


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    common = {"down_days": {"kind": "int", "low": 1, "high": 3, "step": 1},
        "hold_days": {"kind": "int", "low": 3, "high": 8, "step": 1},
        "weak_fraction": {"kind": "float", "low": .25, "high": 1., "step": .05},
        "trail_atr": {"kind": "float", "low": 1.5, "high": 4., "step": .1}}
    extra = {"participation_days": {"kind": "int", "low": 10, "high": 60, "step": 5},
        "participation_threshold": {"kind": "float", "low": .7, "high": 1.6, "step": .05},
        "quiet_fraction": {"kind": "float", "low": .25, "high": .75, "step": .05}}
    for number, original, source_ex, source_name, start_id in (
        (36, "C0067", 24, "trail2p5", 102), (37, "C0101", 35, "threshold110", 150),
    ):
        work = EXPERIMENTS / f"EX{number:03}_20261110"
        assert not (work / "others/execution.json").exists(), "Search already started"
        source = EXPERIMENTS / f"EX{source_ex:03}_20261110"
        config = json.loads((source / "protocols/config.json").read_bytes())
        center = next(x["parameters"] for x in config["candidates"] if x["name"] == source_name)
        if original == "C0101":
            center = {**center, "participation_days": 20}
        config.update(round=number-35, stage="STAGE_THREE", candidates=[],
            controls=[f"research/S019/experiments/EX{source_ex:03}_20261110/others/{source_name}_account.json"],
            primary_warmup=900 if original == "C0101" else 2)
        save(work / "protocols/config.json", config)
        design = {"parent": original, "round": number-35, "trial_budget": 48, "startup_trials": 16,
            "seed": 20261110, "batch_size": 4, "candidate_start": start_id,
            "space": {**common, **(extra if original == "C0101" else {})}, "center": center,
            "sampler": "TPESampler(multivariate=True, constant_liar=True, constraints_func=normalized_gates)",
            "optuna_version": "4.9.0", "objective": "MAXIMIZE_NAR_SUBJECT_TO_ALL_SIX_CENTER_GATES",
            "center_control": config["controls"][0], "stopping": "48 proposals, all outcomes retained; no score-based early stop",
            "pruning": "DISABLED_FULL_CONTINUOUS_ACCOUNTS", "duplicates": "reuse exact evaluated configuration within study",
            "recovery": "Replay deterministic ask/tell batches from seed, verify saved proposals, reuse authenticated account evidence"}
        save(work / "protocols/search.json", design)
        source_strategy = EXPERIMENTS / ("EX031_20261110" if original == "C0101" else "EX024_20261110") / "src/strategy.py"
        (work / "src/strategy.py").write_bytes(source_strategy.read_bytes())
        plan = f"""# {original}联合参数搜索：事前方案

用户已授权新增10轮，并恢复研究、提出C0067与C0101各开展一轮联合搜索。本实验为新授权第{number-35}轮，阶段三。暂停前EX036仅创建目录，未评价账户；原固定点位设计已在计算前由本方案替换。

使用Optuna 4.9.0多变量TPE，48次提议、16次启动覆盖、4个一批，固定seed=20261110。先排入原中心作等价复核，其余启动提议由Optuna产生；每批全部返回后按trial编号反馈，再提出下一批。全部有效参数同时采样，保存每次提议与全部结果。达到48次提议后停止，不因短期成绩选择性延长。研究空间适配源码由既有实现复用，Optuna负责通用搜索算法。

共同参数：连续下跌天数1—3（整数）、持有期限3—8日（整数）、季度弱势仓位0.25—1.00（步长0.05）、ATR跟踪距离1.5—4.0（步长0.1）。C0101增加成交参与跨度10—60日（步长5）、阈值0.70—1.60（步长0.05）、低参与仓位0.25—0.75（步长0.05）。精确适用空间见search.json。范围覆盖此前局部对照的两侧及扩边；允许弱势仓位1形成风险控制删项。固定首30分钟入场、季度63日、ATR14和各自结构，类别/布尔结构保持原值。

目标最大化NAR，以NAR≥55%、Calmar≥5、MDD≤25%且≤买持80%、60日闭合中位数≥6、至少3笔覆盖≥90%作为六项约束。违反量分别按0.55、5、0.25、买持80%、6及0.9归一化，全部≤0为可行。Optuna采样与研究验收分开核对，所有合格配置按未舍入NAR降序。技术失败作为FAIL保留，不填假绩效；完整账户不剪枝。

沿用MANDATE/2：2021预热，2022-01-03至2026-10-30连续已见历史；HFQ整数模拟单位、100000美元初始权益、每侧0.1%费用、限价买入与市价卖出、M30决定。4进程且每进程1个原生线程，每轮单个公共执行会话共享数据与买持。重复配置复用精确账户，实际新账户和提议数分别统计。

两个研究族各48次提议，为相同计算上限的探索比较，维度分别4与7；结果不宣称穷尽空间或证明某结构全局最优。此前开发结果和两轮选择均保留已见历史属性。正式80%参数扰动及阶段四五项自检仍待相应授权。两轮先完成并呈现比较，剩余8轮按研究决定安排。
"""
        (work / "protocols/plan.md").write_bytes(plan.encode())
        (work / "report.md").write_bytes((f"# {original}的Optuna联合参数搜索\n\nStatus: IN_PROGRESS\n\n方案见[事前设计](protocols/plan.md)，运行及完整结果待补。\n").encode())
    print("JOINT_DESIGNS_READY", flush=True)


if __name__ == "__main__":
    main()
