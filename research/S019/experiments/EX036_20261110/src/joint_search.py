"""Optuna proposes joint parameters; public TDR evaluates complete accounts."""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
OWNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OWNER.parent / "EX013_20261110/src"))
from runner import (  # noqa: E402
    save, read_account, metrics, summarize, equity_source_hash,
    EquityStrategyDefinition, EquityStrategyCandidate, RepositoryContext,
    replay_context, HISTORY_START, SOURCE, publish_evidence, d, TimeInterval,
)
import optuna  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def constraints(trial):
    return trial.user_attrs["constraints"]


def gate_values(m, bh):
    return [(0.55-m["nar"])/.55, (5-m["calmar"])/5 if m["calmar"] is not None else 1e6,
        (m["drawdown"]-.25)/.25, m["drawdown"]/(.8*bh["drawdown"])-1,
        (6-m["frequency_median"])/6, (.9-m["frequency_coverage"])/.9]


def check_center(work, name, design):
    _, a = read_account(work / f"others/{name}_account.json")
    _, b = read_account(ROOT / design["center_control"])
    a, b = a["runs"]["candidate"], b["runs"]["candidate"]
    assert a["metrics"] == b["metrics"], "Center account metrics changed"
    # Candidate/decision/cycle identities legitimately change on a new evaluation.
    economic = ("session", "time", "cash", "equity", "quantity", "receivable", "close",
                "bar_status", "valuation_price_at", "valuation_stale", "execution_blocked")
    assert [tuple(x[k] for k in economic) for x in a["account_daily"]] == [tuple(x[k] for k in economic) for x in b["account_daily"]], "Center daily economic path changed"
    assert [(x["execution_start"], x["target"]) for x in a["decisions"]] == [(x["execution_start"], x["target"]) for x in b["decisions"]]
    assert [(x["interval_start"], x["side"], x["quantity"], x["price"], x["fees"]) for x in a["fills"]] == [(x["interval_start"], x["side"], x["quantity"], x["price"], x["fees"]) for x in b["fills"]]
    save(work / "others/center_parity.json", {"status": "PASS", "control": design["center_control"],
        "new_account": f"{name}_account.json", "decisions": len(a["decisions"]), "fills": len(a["fills"])})


def main(experiment):
    assert optuna.__version__ == "4.9.0"
    work = OWNER.parent / experiment
    config, design = read(work / "protocols/config.json"), read(work / "protocols/search.json")
    existing = {row["name"]: row for row in config["candidates"]}
    config["candidates"] = []
    base = read(OWNER.parent / "EX005_20261110/others/common_definition.json")
    base.update(source_sha256=equity_source_hash(work / "src", ("strategy.py",)), state_schema=config["state_schema"],
                warmup_bars=config["primary_warmup"])
    for aux in base["auxiliary_inputs"]:
        aux["warmup_bars"] = 65
    base["auxiliary_inputs"].extend(config["extra_auxiliary_inputs"])
    spec = EquityStrategyDefinition.from_dict({**base, "parameters_json": json.dumps(design["center"]),
        "parameter_schema_json": json.dumps({k: {"type": "boolean" if type(v) is bool else "integer" if type(v) is int else "number" if type(v) is float else "string"} for k, v in design["center"].items()})}).execution_spec
    context = replay_context(RepositoryContext.discover(ROOT), spec)
    exp = d.ExperimentRef("S019", experiment)
    zone = ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2022, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone))
    sampler = optuna.samplers.TPESampler(seed=design["seed"], multivariate=True, constant_liar=True,
        n_startup_trials=design["startup_trials"], constraints_func=constraints)
    study = optuna.create_study(direction="maximize", sampler=sampler, study_name=experiment)
    study.enqueue_trial({k: design["center"][k] for k in design["space"]})
    known, measured, history = {}, {}, []
    started, prepare_seconds, evaluate_seconds = perf_counter(), 0., 0.
    attempts_path = work / "others/attempts.json"
    attempts = read(attempts_path) if attempts_path.exists() else []
    failures = []
    with d.ResearchExecutionSession(context, experiment=exp,
        on_progress=lambda x: print(x, flush=True)) as execution:
        try:
            for batch_start in range(0, design["trial_budget"], design["batch_size"]):
                batch, pending = [], []
                before = perf_counter()
                for _ in range(min(design["batch_size"], design["trial_budget"]-batch_start)):
                    trial = study.ask()
                    suggested = {}
                    for key, bounds in design["space"].items():
                        method = trial.suggest_int if bounds["kind"] == "int" else trial.suggest_float
                        suggested[key] = method(key, bounds["low"], bounds["high"], step=bounds["step"])
                    parameters = {**design["center"], **suggested}
                    fingerprint = json.dumps(parameters, sort_keys=True)
                    duplicate = fingerprint in known
                    if duplicate:
                        row = known[fingerprint]
                    else:
                        row = {"name": f"trial{trial.number:03}", "id": f"C{design['candidate_start']+trial.number:04}", "parameters": parameters}
                        known[fingerprint] = row
                        if row["name"] in existing:
                            assert row == existing[row["name"]], "Deterministic recovery proposal differs"
                        config["candidates"].append(row)
                        definition = EquityStrategyDefinition.from_dict({**base, "parameters_json": json.dumps(parameters),
                            "parameter_schema_json": json.dumps({k: {"type": "boolean" if type(v) is bool else "integer" if type(v) is int else "number" if type(v) is float else "string"} for k, v in parameters.items()})})
                        path = work / f"others/{row['name']}_definition.json"
                        if path.exists():
                            assert read(path) == json.loads(json.dumps(definition.to_dict()))
                        else:
                            save(path, definition.to_dict())
                        if not (work / f"others/{row['name']}_account.json").exists():
                            candidate = EquityStrategyCandidate("S019", row["id"], definition, work / "src")
                            request = d.EquityEvaluationRequest(exp, candidate, window, HISTORY_START,
                                d.EquitySources(SOURCE, SOURCE, SOURCE), 100000., .001,
                                benchmark=d.EvaluationBenchmark(d.EquityBuyHold(spec)), drawdown_basis="SESSION_CLOSE", concentration_basis="MAX_SINGLE")
                            item = context.evaluation.prepare(request, execution=execution)
                            save(work / f"others/{row['name']}_binding.json", item.request.input_binding.to_dict())
                            pending.append((row, item))
                    batch.append((trial, row, duplicate))
                save(work / "protocols/config.json", config)
                proposals = [{"trial": t.number, "parameters": dict(t.params), "account_name": r["name"], "duplicate": dup} for t, r, dup in batch]
                proposal_path = work / f"others/proposals_{batch_start:03}.json"
                if proposal_path.exists():
                    assert read(proposal_path) == proposals
                else:
                    save(proposal_path, proposals)
                prepare_seconds += perf_counter()-before
                if pending:
                    before = perf_counter()
                    outcomes = context.evaluation.evaluate_many(tuple(item for _, item in pending), execution=execution)
                    evaluate_seconds += perf_counter()-before
                    for (row, item), outcome in zip(pending, outcomes, strict=True):
                        if outcome.result is None:
                            failures.append({"name": row["name"], "status": outcome.status.value, "error": str(outcome.error)})
                            continue
                        ref = publish_evidence(context, d.EvaluationEvidenceWrite(exp, row["name"], item, outcome.result), execution=execution)
                        save(work / f"others/{row['name']}_account.json", ref.to_dict())
                for trial, row, duplicate in batch:
                    path = work / f"others/{row['name']}_account.json"
                    if not path.exists():
                        study.tell(trial, state=optuna.trial.TrialState.FAIL)
                        history.append({"trial": trial.number, "parameters": dict(trial.params), "state": "FAIL", "account_name": row["name"]})
                        continue
                    if row["name"] not in measured:
                        ref, payload = read_account(path)
                        run, bh = payload["runs"]["candidate"], payload["runs"]["buy_hold"]
                        bh_dd = bh["metrics"]["daily_max_drawdown"]
                        measured[row["name"]] = {"id": row["id"], "parameters": row["parameters"], "account": ref.to_dict(),
                            "candidate": metrics(run, bh_dd), "buy_hold": metrics(bh, bh_dd)}
                        if trial.number == 0:
                            check_center(work, row["name"], design)
                    record = measured[row["name"]]
                    g = gate_values(record["candidate"], record["buy_hold"])
                    assert (max(g) <= 0) == record["candidate"]["eligible"]
                    trial.set_user_attr("constraints", g)
                    trial.set_user_attr("account", record["account"])
                    study.tell(trial, record["candidate"]["nar"])
                    history.append({"trial": trial.number, "parameters": dict(trial.params), "state": "COMPLETE",
                        "value": record["candidate"]["nar"], "constraints": g, "account_name": row["name"], "duplicate": duplicate})
                save(work / "others/trials.json", {"optuna_version": optuna.__version__, "seed": design["seed"], "trials": history})
                save(work / "others/search_results.json", measured)
                m = max((r["candidate"]["calmar"] or -1 for r in measured.values()))
                print("SEARCH_BATCH", len(history), "unique", len(measured), "eligible", sum(r["candidate"]["eligible"] for r in measured.values()), "max_calmar", m, flush=True)
                if failures:
                    raise RuntimeError(failures)
        finally:
            equity_stats = execution.equity_statistics
            equity_counts = asdict(equity_stats) if equity_stats is not None else {
                "input_snapshots": 0, "candidate_runs": 0, "benchmark_runs": 0, "account_timings": []}
            technical_error = sys.exception()
            attempt = {"resources": {"workers": 4, "native_threads": 1}, "prepare_seconds": prepare_seconds,
                "evaluate_seconds": evaluate_seconds, "total_seconds": perf_counter()-started,
                "statistics": asdict(execution.stats), "equity_statistics": equity_counts, "failures": failures,
                "technical_error": None if technical_error is None else f"{type(technical_error).__name__}: {technical_error}"}
            combined = [*attempts, attempt]
            save(attempts_path, combined)
            total_stats = {key: sum(a["equity_statistics"][key] for a in combined)
                           for key in ("input_snapshots", "candidate_runs", "benchmark_runs")}
            total_stats["account_timings"] = [t for a in combined for t in a["equity_statistics"]["account_timings"]]
            save(work / "others/execution.json", {**attempt, "equity_statistics": total_stats,
                "prepare_seconds": sum(a["prepare_seconds"] for a in combined),
                "evaluate_seconds": sum(a["evaluate_seconds"] for a in combined),
                "total_seconds": sum(a["total_seconds"] for a in combined), "attempt_count": len(combined),
                "statistics_scope": "LAST_ATTEMPT; full per-attempt statistics retained in attempts.json"})
    assert len(history) == design["trial_budget"]
    summarize(work, config)
    summary = read(work / "others/summary.json")
    assert all(summary[name]["candidate"] == row["candidate"] for name, row in measured.items())
    print("JOINT_SEARCH_COMPLETE", design["parent"], len(history), len(summary), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
