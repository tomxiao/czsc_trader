"""Managed S012 research screening with exact-account equivalence gate.

Screening output is explicitly distinct from FULL platform evaluation. All
qualifying configurations require successor FULL before candidate publication.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
import multiprocessing
from pathlib import Path
import sys

import optuna
import numpy as np
import pandas as pd
from dataflows import Dataset
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentDependency, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentCapability,
)
from strategy_runtime import ParameterSet
from .s012_bound_model import S012PlannedCycle, synthetic_selfcheck
from .managed_market import load

EID = 'EX027_20261006'
SEED = 12027
ADAPTIVE_TARGET = 0
MAX_ADAPTIVE_PROPOSALS = 0
BASE = {'allocation': 1.0, 'confirm_o01': False, 'cooldown': 0, 'entry_premium': 0.01, 'hold_days': 5, 'opportunity': 'union', 'risk_exit': False, 'risk_gate': 'none', 'trailing_stop': 0.0}
CHOICES = {
    "opportunity": ["n09", "union", "always"], "confirm_o01": [False, True],
    "risk_gate": ["none", "mom", "vol", "kurt"], "risk_exit": [False, True],
    "trailing_stop": [0., .005, .01, .015, .02, .03, .05, .1, .2],
    "entry_premium": [-.05, -.03, -.02, -.01, -.005, -.002, 0., .002, .0025, .005,
                      .0075, .01, .0125, .015, .02, .03, .05],
    "allocation": [.5, .75, 1.],
}
DOMAINS = {name: {"kind": "CATEGORICAL", "choices": values} for name, values in CHOICES.items()}
DOMAINS.update(hold_days={"kind": "INT", "low": 1, "high": 60, "step": 1},
               cooldown={"kind": "INT", "low": 0, "high": 10, "step": 1})


def grids():
    # Replay the frozen incumbent first. These are local finite contrasts,
    # including previously omitted integer holding periods, not new resources.
    fixed = [dict(BASE)]
    premiums = (.0025, .005, .0075, .01, .0125, .015, .02)
    holds = tuple(sorted({4, 6, 7, 9, BASE["hold_days"]}))
    clear = dict(BASE, opportunity="union", confirm_o01=False, cooldown=0,
                 risk_gate="none", risk_exit=False, trailing_stop=0., allocation=1.)
    for hold in holds:
        for premium in premiums:
            fixed.append(dict(clear, hold_days=hold, entry_premium=premium))
    for hold in tuple(sorted({BASE["hold_days"], 6, 7})):
        for stop in (0., .005, .01, .015, .02, .03, .05):
            for premium in (.0075, .01, .0125):
                fixed.append(dict(clear, hold_days=hold, trailing_stop=stop, entry_premium=premium))
    for hold in holds:
        for premium in (.005, .01, .015, .02):
            fixed.append(dict(clear, hold_days=hold, entry_premium=premium,
                              risk_gate="mom", risk_exit=True))
    for hold in tuple(sorted({4, 6, BASE["hold_days"]})):
        for premium in premiums:
            fixed.append(dict(clear, hold_days=hold, entry_premium=premium, allocation=.75))
    for hold in (7, 9, 10):
        for premium in premiums:
            for allocation in (.75, 1.):
                fixed.append(dict(clear, opportunity="always", hold_days=hold,
                                  entry_premium=premium, allocation=allocation))
    return fixed, []


FIXED, BOUNDARY = grids()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def parameters(trial):
    value = {name: trial.suggest_categorical(name, choices) for name, choices in CHOICES.items()}
    value["hold_days"] = trial.suggest_int("hold_days", 1, 60)
    value["cooldown"] = trial.suggest_int("cooldown", 0, 10)
    return value


def semantic(parameters):
    value = dict(parameters)
    if value["opportunity"] in ("n09", "always"):
        value["confirm_o01"] = False
    if value["risk_gate"] == "none":
        value["risk_exit"] = False
    if value["hold_days"] == 1:
        value.update(risk_exit=False, trailing_stop=0.)
    return value


def capacity(parameters, features, source):
    bounded = dict(parameters)
    early_exit = bool(parameters["risk_exit"] or parameters["trailing_stop"] > 0.)
    if early_exit:
        bounded.update(hold_days=1, cooldown=0, risk_exit=False, trailing_stop=0.)
    strategy = S012PlannedCycle(ParameterSet({**bounded, "rule": {"data_source": source}}))
    sessions = pd.DatetimeIndex(pd.to_datetime(features.Date.iloc[:-1]), name="dt")
    history = strategy.calculate_history({"features": features,
                                         "execution": pd.DataFrame({"Date": features.Date, "Close": 1.})}, sessions)
    return {"closed_cycle_upper_bound": int(history.decision_reason.str.startswith("EXIT_").sum()),
            "kind": "optimistic_h1_no_cooldown" if early_exit else "uniform_causal_planned_cycle",
            "bounded_parameters": bounded, "signal_sessions": len(sessions),
            "prices": "constant 1; no historical returns or future masks",
            "required_closed_cycles": 128}


def verify_gate(exp, root):
    path = exp / "gate.json"
    gate = json.loads(path.read_text(encoding="utf-8"))
    if gate["status"] != "PASS":
        raise ValueError("host equivalence gate did not pass")
    proofs = {}
    for key in ("real_comparison", "synthetic_comparison"):
        ref = gate[key]
        source = (root / ref["path"]).resolve()
        source.relative_to(root)
        if sha256(source.read_bytes()).hexdigest() != ref["sha256"]:
            raise ValueError("equivalence proof changed: " + key)
        proofs[key] = json.loads(source.read_text(encoding="utf-8"))
    real, synthetic = proofs["real_comparison"], proofs["synthetic_comparison"]
    if (real.get("status") != "PASS" or real.get("passed") != 4
            or real.get("experiment_id") != "EX025_20261005"
            or real.get("complete_formal_witness_pass") is not True
            or synthetic.get("status") != "PASS" or len(synthetic.get("cases", [])) != 8
            or any(case["comparison"]["status"] != "PASS" for case in synthetic["cases"])):
        raise ValueError("complete four real/eight synthetic witnesses required")
    for filename, expected in gate["source_sha256"].items():
        if filename not in {"s012_accelerator.py", "s012_bound_model.py"}:
            raise ValueError("unexpected gated source")
        if sha256((exp / filename).read_bytes()).hexdigest() != expected:
            raise ValueError("accelerated code changed after witness validation")
    if set(gate["source_sha256"]) != {"s012_accelerator.py", "s012_bound_model.py"}:
        raise ValueError("gate must bind both strategy and accelerator")
    if (synthetic["accelerator_sha256"] != gate["source_sha256"]["s012_accelerator.py"]
            or real["accelerator_sha256"] != gate["source_sha256"]["s012_accelerator.py"]):
        raise ValueError("synthetic witness accelerator differs")
    original = root / "experiments/S012/EX023_20261005/strategy_runtime/strategies/s012.py"
    if sha256(original.read_bytes()).hexdigest() != gate["source_sha256"]["s012_bound_model.py"]:
        raise ValueError("formal strategy and screening strategy differ")
    return {"host_gate": gate, "gate_sha256": sha256(path.read_bytes()).hexdigest(),
            "status": "PASS", "screening_only": True}


def frontier(rows):
    completed = [row for row in rows if row["status"] == "COMPLETE"]
    nondominated = []
    vectors = np.array([(row["metrics"]["net_cagr"], -abs(row["metrics"]["max_drawdown"]),
                         min(row["metrics"]["frequency"], 5.)) for row in completed], dtype=float)
    for row, vector in zip(completed, vectors):
        dominated = bool((np.all(vectors >= vector, axis=1) & np.any(vectors > vector, axis=1)).any())
        if not dominated:
            nondominated.append(row["proposal_id"])
    feasible = [row for row in completed if row["metrics"]["frequency"] >= 5.
                and abs(row["metrics"]["max_drawdown"]) < abs(row["metrics"]["benchmark"]["max_drawdown"])]
    best = max(feasible, key=lambda row: row["metrics"]["net_cagr"], default=None)
    return {"nondominated_proposals": nondominated,
            "completed": len(completed), "qualified": sum(row["metrics"]["passed_all"] for row in completed),
            "best_frequency_drawdown_feasible": None if best is None else
            {"proposal_id": best["proposal_id"], "parameters": best["parameters"], "metrics": best["metrics"]}}


def phase_statistics(rows):
    result = {}
    for phase in ("FIXED", "ADAPTIVE", "BOUNDARY", "ALL"):
        values = rows if phase == "ALL" else [row for row in rows if row["phase"] == phase]
        completed = [row for row in values if row["status"] == "COMPLETE"]
        best = max(completed, key=lambda row: row["metrics"]["net_cagr"], default=None)
        result[phase] = {
            "proposals": len(values), "completed": len(completed),
            "pruned": sum(row["status"] == "PRUNED" for row in values),
            "failed": sum(row["status"] == "FAILED" for row in values),
            "parameter_sha256_unique": len({row["parameter_sha256"] for row in values}),
            "semantic_parameter_sha256_unique": len({row["semantic_parameter_sha256"] for row in values}),
            "actual_behavior_sha256_unique": len({row["behavior_sha256"] for row in completed}),
            "best_overall_cagr": None if best is None else {"proposal_id": best["proposal_id"],
                "parameters": best["parameters"], "metrics": best["metrics"]},
            "frontier": frontier(values),
        }
    previous = frontier([row for row in rows if row["phase"] != "BOUNDARY"])["best_frequency_drawdown_feasible"]
    final = result["ALL"]["frontier"]["best_frequency_drawdown_feasible"]
    improvement = None if final is None or previous is None else final["metrics"]["net_cagr"] - previous["metrics"]["net_cagr"]
    all_best = result["ALL"]["best_overall_cagr"]
    boundary_contacts = []
    for category, best in (("overall", all_best), ("frequency_drawdown_feasible", final)):
        if best is not None:
            p = best["parameters"]
            contacts = [name for name, extreme in (("hold_days", (60,)), ("cooldown", (10,)),
                        ("entry_premium", (-.05, .05)), ("trailing_stop", (.005, .2))) if p[name] in extreme]
            if contacts:
                boundary_contacts.append({"category": category, "proposal_id": best["proposal_id"], "fields": contacts})
    promising = bool(improvement is not None and improvement > .005)
    result["boundary_assessment"] = {"feasible_cagr_improvement": improvement,
        "best_boundary_contacts": boundary_contacts,
        "successor_optimization_required": promising or bool(boundary_contacts),
        "successor_full_required": True,
        "reason": "boundary improvement/contact needs mechanism-specific extension before adequacy claim"
                  if promising or boundary_contacts else "planned boundary contrasts complete; evaluate target gap and actual FULL before closure"}
    return result


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2, EID, "S012", ExperimentMode.FORMAL,
            "冻结最强可行策略的相邻持有日、限价、退出与中间仓位能否改善净收益目标差距？",
            "前驱最强可行联合h5策略有132闭合与10.29%净年化；相邻整数持有期及成交限价可检验网格遗漏和费用权衡，全部达标仍须正式FULL。",
            ("净年化达到BuyHold的1.5倍、回撤严格更小、1535日分母至少128闭合必须同时成立。",
             "若容量、费用及参数边界证据均显示稳定目标差距，则记录当前组件路线失败与改进所需条件。"),
            date(2026, 9, 30), SEED,
            tuple(dataset.value for dataset in (Dataset.STRATEGY_FEATURE_EVIDENCE, Dataset.ETF_OHLCV,
                  Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY, Dataset.TRADING_CALENDAR)),
            ExperimentProtocol(
                ExperimentStage.PARAMETER_SEARCH,
                ("518850/S012已见开发池，原费用、100股、100000元、原1535频率分母与基准不变。",),
                (f"{len(FIXED)}预先声明局部固定对照，含冻结真实incumbent复现、hold4/6/7/9、相邻premium/拖尾/mom退出、75%仓与always反证；零随机提案。",),
                ("Optuna TPE多目标净CAGR最大、回撤幅度最小、min(频率,5)最大；三项原经济门共同判断。",),
                ("held1..60/cool0..10/premium±5%/trailing0..20%/half-full静态仓位，风险与确认组合。",),
                ("4个真实FULL与8个合成账本逐项比较通过才启用，平台源码保持不变。",
                 "只在参数语义等价或因果闭合周期乐观上界<128时PRUNED，所有失败及重复参数完整记录。",
                 "4普通spawn worker且原生线程1，父进程集中Optuna tell保证提案顺序可复算。",
                 "所有逐日账户、信号、计划、订单、成交及开放交易原样gzip保存，screening不伪装FULL。",
                 "封存EX026已计算完整search、manifest与post-compute failure作为selector，保留正式失败意义并继承真实全部台账；局部边界不等于原授权外边界，不以预算声明充分。",
                 "筛选达标全部进入后继FULL；无达标确认2—4个最强收益/可行前沿，正式失败亦纳入交付。"),
                predecessor_experiment_ids=("EX017_20261005", "EX018_20261005", "EX019_20261005", "EX025_20261005")),
            ExperimentDataScope.DEVELOPMENT, subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(package, version(package)) for package in ("numpy", "pandas", "optuna")),
            capabilities=ExperimentCapabilities(reads_real_returns=True, searches_parameters=True,
                                               selects_parameters=True, creates_candidate=False))

    def synthetic_precheck(self):
        facts = synthetic_selfcheck()
        assert 150 <= len(FIXED) <= 250
        assert not BOUNDARY and ADAPTIVE_TARGET == 0
        for parameters_ in (*FIXED, *BOUNDARY):
            for name, values in CHOICES.items():
                assert parameters_[name] in values
            assert 1 <= parameters_["hold_days"] <= 60 and 0 <= parameters_["cooldown"] <= 10
        return ExperimentPrecheckResult(
            (ExperimentPreflightCheck("CAUSAL_SOURCE_AND_DECLARED_SEARCH_DOMAIN", ExperimentPreflightStatus.PASS, str(facts)),),
            ExperimentResult(ExperimentOutcome.INCONCLUSIVE, facts, {"scope": "synthetic only; gate checked before real reads"}))

    def execute(self, context):
        for capability in (ExperimentCapability.SEARCH_PARAMETERS, ExperimentCapability.SELECT_PARAMETERS):
            context.record_capability(capability)
        root, exp = Path.cwd().resolve(), Path(__file__).resolve().parent
        proof = verify_gate(exp, root)
        anchor = json.loads((exp / "anchor.json").read_text(encoding="utf-8"))
        parent = root / "experiments/S012/EX026_20261006/artifacts/rex"
        manifest_path = parent.parent.parent / "experiment_manifest.json"
        if sha256(manifest_path.read_bytes()).hexdigest() != anchor["parent_manifest_sha256"]:
            raise ValueError("sealed failed-parent manifest changed")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256((parent / "search.json").read_bytes()).hexdigest() != anchor["search_sha256"]:
            raise ValueError("frozen parent search changed")
        if manifest["files"]["artifacts/rex/search.json"]["sha256"] != anchor["search_sha256"]:
            raise ValueError("parent search absent from sealed manifest")
        import shutil
        inherited = {
            "legacy_search.json": (parent / "search.json", anchor["search_sha256"]),
            "legacy_execution_failure.json": (parent / "execution_failure.json", anchor["failure_sha256"]),
            "legacy_post_compute_failure.json": (parent.parent.parent / "post_compute_failure.json", anchor["post_compute_failure_sha256"]),
            "legacy_experiment_manifest.json": (manifest_path, anchor["parent_manifest_sha256"]),
            "inherited_search_bundle.tar.gz": (parent.parent.parent / "inherited_search_bundle.tar.gz", anchor["bundle_sha256"]),
        }
        for name, (path, expected) in inherited.items():
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("sealed failed-parent inherited file changed: " + name)
            shutil.copyfile(path, context.workspace.path(name))
        data, market = load(context)
        feature = exp / "strategy_runtime/resources/features.csv"
        original = root / "experiments/S012/EX023_20261005/strategy_runtime/resources/features.csv"
        feature_sha = sha256(feature.read_bytes()).hexdigest()
        if feature_sha != sha256(original.read_bytes()).hexdigest():
            raise ValueError("stage-two causal features changed")
        features = pd.read_csv(feature, parse_dates=["Date"])
        assert len(features) == 1535 and len(data.evaluation_sessions) == 1534
        source = {"package": "strategy_runtime", "path": "resources/features.csv", "sha256": feature_sha}
        witness = json.loads((root / "experiments/S012/EX025_20261005/artifacts/rex/trials.json").read_text(encoding="utf-8"))
        benchmarks = [row["metrics"]["benchmark"] for row in witness]
        benchmark = benchmarks[0]
        if len(benchmarks) != 4 or any(canonical(value) != canonical(benchmark) for value in benchmarks):
            raise ValueError("full witness benchmark mismatch")
        proof.update(feature_sha256=feature_sha, market_fingerprint=data.fingerprint,
                     input_identities=data.input_identities, actual_market_prepared=str(data.prepared),
                     benchmark=benchmark, all_input_data_seen=True,
                     formal_source_root="experiments/S012/EX023_20261005/strategy_runtime")
        write(context.workspace.path("screening_provenance.json"), proof)
        if str(exp) not in sys.path:
            sys.path.insert(0, str(exp))
        import s012_search_worker as worker
        study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=SEED, n_startup_trials=12),
                                    directions=("maximize", "minimize", "maximize"))
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        proposals, seen, checkpoints = [], {}, []
        adaptive_completed, adaptive_proposals = 0, 0
        output = context.workspace.root

        def snapshot(stop_reason):
            sorted_rows = sorted(proposals, key=lambda row: row["trial_number"])
            search = {"search_id": EID + "_SCREENING_TPE", "domains": DOMAINS,
                      "method": "Optuna enqueue-only fixed local contrasts", "method_version": optuna.__version__,
                      "seed": SEED, "scheduling": "deterministic batch of 4; main-process tell in ask order; spawn/native1",
                      "declared_budget": len(FIXED) + MAX_ADAPTIVE_PROPOSALS + len(BOUNDARY),
                      "budget_details": {"fixed": len(FIXED), "adaptive_successful_unique": ADAPTIVE_TARGET,
                                         "adaptive_proposal_cap": MAX_ADAPTIVE_PROPOSALS, "boundary": len(BOUNDARY)},
                      "mode": "RESEARCH_SCREENING_EQUIVALENT_SUBSET_NOT_FULL",
                      "stop_reason": stop_reason, "proposals": sorted_rows, "checkpoints": checkpoints,
                      "frontier": frontier(sorted_rows), "adaptive_completed": adaptive_completed,
                      "adaptive_proposals": adaptive_proposals,
                      "qualified_proposals": [row["proposal_id"] for row in sorted_rows if row.get("passed_all")],
                      "publication_rule": "Every screening qualifier requires actual successor FULL; no screening Candidate identity."}
            write(context.workspace.path("search.json"), search)
            return search

        with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn"),
                                 initializer=worker.initialize,
                                 initargs=(features, data.execution_daily, data.execution_intraday,
                                           source, str(output), benchmark)) as pool:
            for phase, fixed in (("FIXED", FIXED), ("ADAPTIVE", None), ("BOUNDARY", BOUNDARY)):
                if fixed is not None:
                    for parameters_ in fixed:
                        study.enqueue_trial(parameters_)
                asked_in_phase = 0
                while (asked_in_phase < len(fixed) if fixed is not None else
                       adaptive_completed < ADAPTIVE_TARGET and adaptive_proposals < MAX_ADAPTIVE_PROPOSALS):
                    pending = []
                    while len(pending) < 4 and (asked_in_phase < len(fixed) if fixed is not None else
                           adaptive_completed + len(pending) < ADAPTIVE_TARGET and adaptive_proposals < MAX_ADAPTIVE_PROPOSALS):
                        trial = study.ask()
                        values = parameters(trial)
                        asked_in_phase += 1
                        if fixed is None:
                            adaptive_proposals += 1
                        normalized = semantic(values)
                        equivalent_sha = sha256(canonical(normalized)).hexdigest()
                        bound = capacity(values, features, source)
                        row = {"proposal_id": f"OPTUNA_{trial.number:04d}", "trial_number": trial.number,
                               "number": trial.number, "phase": phase, "parameters": values,
                               "parameter_sha256": sha256(canonical(values)).hexdigest(),
                               "semantic_parameter_sha256": equivalent_sha,
                               "capacity_proof": bound, "candidate": None, "passed_all": False}
                        if equivalent_sha in seen or bound["closed_cycle_upper_bound"] < 128:
                            row.update(status="PRUNED", reason=("causal parameter semantic equivalence"
                                       if equivalent_sha in seen else "causal optimistic closed-cycle capacity <128"))
                            if equivalent_sha in seen:
                                row["equivalent_proposal_id"] = seen[equivalent_sha]
                            proposals.append(row)
                            study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                            continue
                        seen[equivalent_sha] = row["proposal_id"]
                        pending.append((trial, row, pool.submit(worker.evaluate, trial.number, values)))
                    for trial, row, future in pending:
                        result = future.result()
                        row.update(result)
                        if result["status"] == "COMPLETE":
                            metrics = result["metrics"]
                            row["passed_all"] = metrics["passed_all"]
                            row["reason"] = "equivalence-gated complete research account; successor FULL required"
                            study.tell(trial, (metrics["net_cagr"], abs(metrics["max_drawdown"]), min(metrics["frequency"], 5.)))
                            if phase == "ADAPTIVE":
                                adaptive_completed += 1
                        else:
                            study.tell(trial, state=optuna.trial.TrialState.FAIL)
                        proposals.append(row)
                        print("SCREENING_ACCOUNT", phase, row["proposal_id"], row["status"],
                              row.get("metrics", {}).get("net_cagr"), row.get("metrics", {}).get("frequency"), flush=True)
                    snapshot("RUNNING; no research closure yet")
                checkpoints.append({"phase": phase, "asked": asked_in_phase,
                                    "frontier": frontier(proposals), "adaptive_completed": adaptive_completed,
                                    "qualified": sum(row.get("passed_all", False) for row in proposals)})
                snapshot("PHASE_COMPLETE; successor FULL and interpretation required")
        search = snapshot("Frozen-incumbent replay and declared local holding/limit/exit/allocation counterfactuals executed. Compare observed local improvement and economic target gap; budget alone is not adequacy. All qualifying configurations or strongest nonqualifying frontiers require successor actual FULL; promising local-edge improvement requires justified continuation.")
        search["phase_statistics"] = phase_statistics(proposals)
        anchor_replays = [row for row in proposals if row["status"] == "COMPLETE"
                          and canonical(row["parameters"]) == canonical(anchor["parameters"])]
        if len(anchor_replays) != 1:
            raise ValueError("exact frozen incumbent replay missing or duplicated")
        replay = anchor_replays[0]
        for name in ("net_cagr", "max_drawdown", "frequency", "final_equity", "total_fees", "exposure"):
            if abs(replay["metrics"][name] - anchor["metrics"][name]) > 1e-8:
                raise ValueError("frozen incumbent replay differs: " + name)
        if replay["metrics"]["closed_trades"] != anchor["metrics"]["closed_trades"]:
            raise ValueError("frozen incumbent closed-cycle count differs")
        if replay["behavior_sha256"] != anchor["behavior_sha256"]:
            raise ValueError("frozen incumbent complete transaction behavior differs")
        final = search["frontier"]["best_frequency_drawdown_feasible"]
        old_cagr = anchor["metrics"]["net_cagr"]
        new_cagr = old_cagr if final is None else final["metrics"]["net_cagr"]
        target_cagr = anchor["metrics"]["benchmark"]["cagr"] * 1.5
        touches = []
        if final is not None:
            p = final["parameters"]
            if p["entry_premium"] in (.0025, .02):
                touches.append("local_premium_edge_inside_original_authorized_continuous_range")
            if p["trailing_stop"] == .05:
                touches.append("local_trailing_edge_inside_original_range")
            if p["hold_days"] == max(4, 6, 7, 9, BASE["hold_days"]):
                touches.append("local_holding_period_edge")
        local = {"anchor_replay": "PASS", "anchor_proposal_id": anchor["proposal_id"],
                 "anchor_replay_proposal_id": replay["proposal_id"],
                 "feasible_cagr_improvement": new_cagr - old_cagr,
                 "target_net_cagr": target_cagr,
                 "target_gap_before": target_cagr - old_cagr,
                 "target_gap_after": target_cagr - new_cagr,
                 "local_contacts": touches,
                 "successor_full_required": True,
                 "successor_optimization_required": new_cagr > old_cagr + 1e-8 and bool(touches)
                                                     and new_cagr < target_cagr,
                 "reason": "Any qualifying configuration needs actual FULL. Further local refinement requires observed improvement at a local edge; allocation .75 is an interior contrast, not an outer boundary."}
        search["phase_statistics"]["boundary_assessment"] = local
        search["successor_required"] = local
        search["parent_selector"] = anchor
        search["search_route"] = "TARGETED_FIXED_LOCAL_NEIGHBORS"
        search["method"] = "Optuna enqueue-only fixed local contrasts; no random proposals"
        write(context.workspace.path("search.json"), search)
        artifacts = [context.workspace.register_artifact(name, "research_screening_account_search")
                     for name in ("search.json", "screening_provenance.json")]
        for name in inherited:
            artifacts.append(context.workspace.register_artifact(name, "honest_failed_predecessor_complete_search_bundle"))
        for path in sorted((output / "screening_ledgers").rglob("*")):
            if path.is_file():
                artifacts.append(context.workspace.register_artifact(path.relative_to(output).as_posix(), "complete_research_screening_ledger"))
        complete = sum(row["status"] == "COMPLETE" for row in proposals)
        failed = sum(row["status"] == "FAILED" for row in proposals)
        return ExperimentResult(ExperimentOutcome.PASS if complete and not failed else ExperimentOutcome.FAIL,
                                {"proposals": len(proposals), "screening_accounts": complete,
                                 "pruned": sum(row["status"] == "PRUNED" for row in proposals),
                                 "failed": failed, "qualified_screening": len(search["qualified_proposals"]),
                                 "adaptive_completed": adaptive_completed},
                                {"mode": "SCREENING_NOT_FULL", "all_input_data_seen": True,
                                 "requires_successor_full": True}, tuple(artifacts))
