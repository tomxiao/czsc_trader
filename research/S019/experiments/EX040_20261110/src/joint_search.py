"""Constrained joint TPE with authenticated prior observations and deterministic recovery."""
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK.parent / "EX013_20261110/src"))
from runner import (  # noqa: E402
    save, read_account, metrics, equity_source_hash, EquityStrategyDefinition,
    EquityStrategyCandidate, RepositoryContext, replay_context, HISTORY_START,
    SOURCE, publish_evidence, d, TimeInterval,
)
import numpy as np  # noqa: E402
import optuna  # noqa: E402
from strategy_evaluator import performance_metrics  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def fingerprint(parameters):
    return json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)


def json_form(value):
    return json.loads(json.dumps(value, allow_nan=False))


def constraints(trial):
    return trial.user_attrs["constraints"]


def gate_values(m, bh):
    assert bh["drawdown"] > 0
    return [(.55-m["nar"])/.55, (5-m["calmar"])/5 if m["calmar"] is not None else 1e6,
        (m["drawdown"]-.25)/.25, m["drawdown"]/(.8*bh["drawdown"])-1,
        (6-m["frequency_median"])/6, (.9-m["frequency_coverage"])/.9]


def authenticated(reference):
    ref = d.EvidenceRef.from_dict(reference)
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    return ref, json.loads(raw)


def validate_measurement(measured, fact):
    """Check supplied original measurements against already-published public facts."""
    daily = fact["account"]
    values = np.asarray([fact["initial_cash"], *[x["equity"] for x in daily]])
    calculated = performance_metrics(values[1:]/values[:-1]-1)
    np.testing.assert_allclose([measured["nar"], measured["drawdown"], measured["calmar"]],
        [calculated.cagr, -calculated.max_drawdown, calculated.calmar], atol=1e-12, rtol=1e-12)
    assert len(daily) == 1212 and daily[0]["session"] == "2022-01-03" and daily[-1]["session"] == "2026-10-30"
    dates = [x["session"] for x in daily]
    exits = [x["exit_session"] for x in fact["closed_cycles"]]
    counts = [sum(dates[i] <= day <= dates[i+59] for day in exits) for i in range(len(dates)-59)]
    assert measured["closed_cycles"] == len(exits)
    assert measured["frequency_median"] == float(np.median(counts))
    assert measured["frequency_coverage"] == sum(x >= 3 for x in counts)/len(counts)
    assert measured["fees"] == float(sum(x["fees"] for x in fact["fills"]))
    ledger = json.loads(fact["equity"]["candidate_ledger"])
    bars = np.asarray([fact["initial_cash"], *[x["equity"] for x in ledger["account_points"]]])
    np.testing.assert_allclose(measured["bar_drawdown"], -performance_metrics(bars[1:]/bars[:-1]-1).max_drawdown,
        atol=1e-12, rtol=1e-12)
    previous = fact["initial_cash"]
    for year, observed in measured["year_returns"].items():
        end = [x["equity"] for x in daily if x["session"].startswith(year)][-1]
        assert observed == end/previous-1
        previous = end


def load_inputs():
    assert optuna.__version__ == "4.9.0"
    config, design = (read(WORK / f"protocols/{name}.json") for name in ("config", "search"))
    priors = read(WORK / design["prior_path"])
    assert len(priors) == design["prior_observations"] == 81
    assert design["trial_budget"] == 48 and design["batch_size"] == 4 and design["candidate_start"] == 334
    assert (WORK / "src/strategy.py").read_bytes() == (WORK.parent / "EX038_20261110/src/strategy.py").read_bytes()
    source_hash = equity_source_hash(WORK / "src", ("strategy.py",))
    request_ref, projection = authenticated(read(WORK.parent / "EX039_20261110/others/assessment_request_ref.json"))
    facts = {x["result_sha256"]: x for x in projection["evidence"]}
    prior_map, benchmarks = {}, {}
    distributions = {key: optuna.distributions.FloatDistribution(x["low"], x["high"], step=x["step"])
        for key, x in design["space"].items()}
    for index, prior in enumerate(priors):
        ref, header = authenticated(prior["account_ref"])
        definition = EquityStrategyDefinition.from_dict(prior["definition"])
        candidate = EquityStrategyCandidate("S019", prior["candidate_id"], definition, WORK / "src")
        assert definition.source_sha256 == source_hash
        assert candidate.content_identity.content_sha256 == prior["content_hash"] == header["request"]["content_sha256"]
        assert header["request"]["candidate_id"] == prior["candidate_id"]
        assert header["request"]["candidate_definition"] == json_form(definition.to_dict())
        assert json.loads(definition.parameters_json) == prior["parameters"]
        assert header["request"]["fee_rate"] == .001 and header["request"]["scenario_id"] == "STANDARD"
        assert {k:v for k,v in prior["parameters"].items() if k not in distributions} == {
            k:v for k,v in design["center"].items() if k not in distributions}
        for key, bounds in design["space"].items():
            value = Decimal(str(prior["parameters"][key]))
            low, high, step = (Decimal(str(bounds[k])) for k in ("low", "high", "step"))
            assert low <= value <= high and (value-low) % step == 0
        fact = facts[ref.sha256]
        assert fact["candidate"]["content_sha256"] == prior["content_hash"]
        validate_measurement(prior["candidate"], fact)
        bh_key = header["benchmark_ref"]["sha256"]
        if bh_key not in benchmarks:
            raw = ref.resolve(ROOT).with_name(bh_key+".json").read_bytes()
            assert sha256(raw).hexdigest() == bh_key
            run = json.loads(raw)["run"]
            benchmarks[bh_key] = metrics(run, run["metrics"]["daily_max_drawdown"])
        bh = benchmarks[bh_key]
        if "benchmark" in prior:
            assert bh == prior["benchmark"]
        else:
            source_summary = read(ROOT / f"research/S019/experiments/{ref.experiment.experiment_id}/others/summary.json")
            assert source_summary[ref.name]["buy_hold"] == bh
        g = gate_values(prior["candidate"], bh)
        assert (max(g) <= 0) == prior["candidate"]["eligible"]
        assert list(prior["candidate"]["gates"].values()) == [x <= 0 for x in g]
        prior["buy_hold"] = bh
        prior["constraints"] = g
        prior["imported_optuna_number"] = index
        fp = fingerprint(prior["parameters"])
        assert fp not in prior_map
        prior_map[fp] = prior
    control = prior_map[fingerprint(design["center"])]
    assert control["candidate_id"] == design["parent"] == "C0300"
    assert read(ROOT / design["center_control"]) == control["account_ref"]
    manifest = {"version": 1, "runner_sha256": digest(Path(__file__)),
        "source_sha256": source_hash, "search_sha256": digest(WORK / "protocols/search.json"),
        "prior_sha256": digest(WORK / design["prior_path"]), "projection": request_ref.to_dict(),
        "config_static_sha256": sha256(fingerprint({k:v for k,v in config.items() if k != "candidates"}).encode()).hexdigest(),
        "optuna_version": optuna.__version__, "prior_count": len(priors)}
    return config, design, priors, prior_map, distributions, manifest


def make_study(design, priors, distributions):
    sampler = optuna.samplers.TPESampler(seed=design["seed"], multivariate=True, constant_liar=True,
        n_startup_trials=design["startup_trials"], constraints_func=constraints)
    study = optuna.create_study(direction="maximize", sampler=sampler, study_name=WORK.name)
    for prior in priors:
        study.add_trial(optuna.trial.create_trial(params={key:prior["parameters"][key] for key in distributions},
            distributions=distributions, value=prior["candidate"]["nar"],
            user_attrs={"constraints": prior["constraints"], "source": prior},
            system_attrs={"constraints": prior["constraints"]}))
    study.enqueue_trial({key: design["center"][key] for key in distributions})
    return study


def check_center(name, design):
    _, a = read_account(WORK / f"others/{name}_account.json")
    _, b = read_account(ROOT / design["center_control"])
    a, b = a["runs"]["candidate"], b["runs"]["candidate"]
    assert a["metrics"] == b["metrics"], "Center metrics changed"
    economic = ("session", "time", "cash", "equity", "quantity", "receivable", "close",
        "bar_status", "valuation_price_at", "valuation_stale", "execution_blocked")
    for key in ("account_daily", "account_points"):
        assert [tuple(x[k] for k in economic) for x in a[key]] == [tuple(x[k] for k in economic) for x in b[key]]
    assert [(x["execution_start"], x["target"]) for x in a["decisions"]] == [(x["execution_start"], x["target"]) for x in b["decisions"]]
    columns = ("interval_start", "side", "quantity", "price", "fees")
    assert [tuple(x[k] for k in columns) for x in a["fills"]] == [tuple(x[k] for k in columns) for x in b["fills"]]
    save(WORK / "others/center_parity.json", {"status": "PASS", "control": design["center_control"],
        "new_account": f"{name}_account.json", "decisions": len(a["decisions"]), "fills": len(a["fills"]),
        "daily_and_bar_economic_paths": "EXACT_EQUAL", "new_candidate_id": "C0334"})


def basic_audit(run):
    assert all(x["observed_through"] <= x["decision_at"] <= x["execution_start"] and 0 <= x["target"] <= 1 for x in run["decisions"])
    assert all(x["cash"] >= -1e-8 and x["quantity"] >= 0 for x in run["account_points"])
    assert all(x["quantity"] > 0 and x["quantity"] == int(x["quantity"]) for x in run["fills"])
    return {"chronology": "PASS", "cash_longonly_integer": "PASS", "source_hash": "PASS"}


def save_or_check(path, value):
    value = json_form(value)
    if path.exists():
        assert read(path) == value, f"Deterministic recovery differs: {path.name}"
    else:
        save(path, value)


def main(preflight=False):
    validation_started = perf_counter()
    config, design, priors, prior_map, distributions, manifest = load_inputs()
    study = make_study(design, priors, distributions)
    if preflight:
        first = study.ask()
        values = {key:first.suggest_float(key, b["low"], b["high"], step=b["step"]) for key,b in design["space"].items()}
        assert first.number == 81 and values == {k:design["center"][k] for k in distributions}
        assert all(tuple(t.system_attrs["constraints"]) == tuple(t.user_attrs["constraints"]) for t in study.trials[:81])
        print("PREFLIGHT_PASS", json.dumps({"priors":81, "new_proposals":48, "first_optuna_number":81,
            "first_candidate":"C0334", "prior_center_eligible":sum(x["candidate"]["eligible"] for x in priors),
            "seconds":perf_counter()-validation_started, "new_accounts":0, "manifest":manifest}), flush=True)
        return
    save_or_check(WORK / "others/run_manifest.json", manifest)
    save_or_check(WORK / "others/imported_trials.json", {"observations":priors, "manifest":manifest})
    existing = {row["name"]:row for row in config["candidates"]}
    config["candidates"] = []
    base = prior_map[fingerprint(design["center"])]["definition"]
    spec = EquityStrategyDefinition.from_dict(base).execution_spec
    context = replay_context(RepositoryContext.discover(ROOT), spec)
    exp, zone = d.ExperimentRef("S019", WORK.name), ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2022,1,3,9,30,tzinfo=zone), datetime(2026,10,30,16,tzinfo=zone))
    used, measured, history, failures = {}, {}, [], []
    started, prepare_seconds, evaluate_seconds = perf_counter(), 0., 0.
    attempts_path = WORK / "others/attempts.json"
    attempts = read(attempts_path) if attempts_path.exists() else []
    results_path, checkpoint_path = WORK / "others/search_results.json", WORK / "others/trials.json"
    assert results_path.exists() == checkpoint_path.exists(), "Incomplete result/checkpoint pair; inspect before recovery"
    saved_results = read(results_path) if results_path.exists() else {}
    if results_path.exists():
        checkpoint = read(checkpoint_path)
        assert checkpoint["manifest"] == manifest
        assert checkpoint["results_sha256"] == digest(results_path)
    with d.ResearchExecutionSession(context, experiment=exp, on_progress=lambda x:print(x,flush=True)) as execution:
        try:
            for batch_start in range(0,48,4):
                batch, pending = [], []
                before = perf_counter()
                for index in range(batch_start,min(batch_start+4,48)):
                    trial = study.ask()
                    assert trial.number == 81+index
                    suggested = {key:trial.suggest_float(key,b["low"],b["high"],step=b["step"]) for key,b in design["space"].items()}
                    # Express the declared decimal grid exactly in account parameters.
                    effective = {}
                    for key, value in suggested.items():
                        b = design["space"][key]
                        steps = round((value-b["low"])/b["step"])
                        effective[key] = float(Decimal(str(b["low"])) + steps*Decimal(str(b["step"])))
                        assert abs(value-effective[key]) < 1e-12
                    parameters = {**design["center"], **effective}
                    fp = fingerprint(parameters)
                    duplicate = fp in used
                    if duplicate:
                        row = used[fp]
                    else:
                        prior = prior_map.get(fp) if index != 0 else None
                        row = {"name":f"trial{index:03}", "id":prior["candidate_id"] if prior else f"C{334+index:04}", "parameters":parameters}
                        used[fp] = row
                        if row["name"] in existing:
                            assert existing[row["name"]] == row
                        config["candidates"].append(row)
                        definition = EquityStrategyDefinition.from_dict(prior["definition"] if prior else {
                            **base, "parameters_json":fingerprint(parameters)})
                        save_or_check(WORK / f"others/{row['name']}_definition.json", definition.to_dict())
                        account_path = WORK / f"others/{row['name']}_account.json"
                        if prior:
                            save_or_check(account_path, prior["account_ref"])
                            measured[row["name"]] = {"id":row["id"], "parameters":parameters,
                                "account":prior["account_ref"], "candidate":prior["candidate"], "buy_hold":prior["buy_hold"],
                                "audit":{"source_hash":"PASS", "measurement_projection":"PASS", "prior_account_reused":True},
                                "provenance":{"kind":"PRIOR_REUSE", "prior_name":prior["name"], "prior_optuna_number":prior["imported_optuna_number"]}}
                        elif account_path.exists():
                            ref, header = authenticated(read(account_path))
                            assert header["request"]["candidate_id"] == row["id"] and header["request"]["candidate_definition"] == json_form(definition.to_dict())
                            if row["name"] in saved_results:
                                record = saved_results[row["name"]]
                                assert record["account"] == ref.to_dict() and record["parameters"] == parameters and record["id"] == row["id"]
                                measured[row["name"]] = record
                        else:
                            candidate = EquityStrategyCandidate("S019",row["id"],definition,WORK/"src")
                            request = d.EquityEvaluationRequest(exp,candidate,window,HISTORY_START,d.EquitySources(SOURCE,SOURCE,SOURCE),
                                100000.,.001,benchmark=d.EvaluationBenchmark(d.EquityBuyHold(spec)),
                                drawdown_basis="SESSION_CLOSE",concentration_basis="MAX_SINGLE")
                            item = context.evaluation.prepare(request,execution=execution)
                            save(WORK/f"others/{row['name']}_binding.json",item.request.input_binding.to_dict())
                            pending.append((row,item))
                    batch.append((index,trial,row,duplicate,suggested))
                save(WORK/"protocols/config.json",config)
                proposals = [{"proposal_index":i,"trial":t.number,"parameters":dict(t.params),"effective_parameters":r["parameters"],
                    "account_name":r["name"],"candidate_id":r["id"],"duplicate":dup} for i,t,r,dup,_ in batch]
                save_or_check(WORK/f"others/proposals_{batch_start:03}.json",proposals)
                prepare_seconds += perf_counter()-before
                if pending:
                    before = perf_counter()
                    outcomes = context.evaluation.evaluate_many(tuple(item for _,item in pending),execution=execution)
                    evaluate_seconds += perf_counter()-before
                    for (row,item),outcome in zip(pending,outcomes,strict=True):
                        if outcome.result is None:
                            failures.append({"name":row["name"],"status":outcome.status.value,"error":str(outcome.error)})
                            continue
                        ref = publish_evidence(context,d.EvaluationEvidenceWrite(exp,row["name"],item,outcome.result),execution=execution)
                        save(WORK/f"others/{row['name']}_account.json",ref.to_dict())
                for index,trial,row,duplicate,suggested in batch:
                    path = WORK/f"others/{row['name']}_account.json"
                    if not path.exists():
                        study.tell(trial,state=optuna.trial.TrialState.FAIL)
                        history.append({"proposal_index":index,"trial":trial.number,"state":"FAIL","parameters":suggested,"account_name":row["name"]})
                        continue
                    if row["name"] not in measured:
                        ref,payload = read_account(path)
                        run,bh = payload["runs"]["candidate"],payload["runs"]["buy_hold"]
                        bh_dd = bh["metrics"]["daily_max_drawdown"]
                        measured[row["name"]] = {"id":row["id"],"parameters":row["parameters"],"account":ref.to_dict(),
                            "candidate":metrics(run,bh_dd),"buy_hold":metrics(bh,bh_dd),"audit":basic_audit(run),
                            "provenance":{"kind":"NEW_ACCOUNT","proposal_index":index,"optuna_number":trial.number}}
                    if index == 0:
                        check_center(row["name"],design)
                    record = measured[row["name"]]
                    g = gate_values(record["candidate"],record["buy_hold"])
                    assert (max(g)<=0) == record["candidate"]["eligible"]
                    trial.set_user_attr("constraints",g)
                    trial.set_user_attr("account",record["account"])
                    study.tell(trial,record["candidate"]["nar"])
                    history.append({"proposal_index":index,"trial":trial.number,"state":"COMPLETE","parameters":suggested,
                        "effective_parameters":row["parameters"],"value":record["candidate"]["nar"],"constraints":g,
                        "account_name":row["name"],"candidate_id":row["id"],"account":record["account"],
                        "duplicate":duplicate,"source_kind":record["provenance"]["kind"]})
                save(WORK/"others/search_results.json",measured)
                save(WORK/"others/summary.json",measured)
                save(WORK/"others/trials.json",{"optuna_version":optuna.__version__,"seed":design["seed"],"imported_count":81,
                    "new_proposal_count":len(history),"trials":history,"results_sha256":digest(WORK/"others/search_results.json"),
                    "manifest":manifest})
                print("SEARCH_BATCH",len(history),"unique_used",len(measured),"eligible",sum(x["candidate"]["eligible"] for x in measured.values()),flush=True)
                if failures:
                    raise RuntimeError(failures)
        finally:
            equity_statistics = execution.equity_statistics
            eq = asdict(equity_statistics) if equity_statistics is not None else {
                "input_snapshots":0, "candidate_runs":0, "benchmark_runs":0, "account_timings":[]}
            error = sys.exception()
            attempt = {"resources":{"workers":4,"native_threads":1},"prepare_seconds":prepare_seconds,
                "evaluate_seconds":evaluate_seconds,"total_seconds":perf_counter()-started,
                "validation_seconds":started-validation_started,"statistics":asdict(execution.stats),"equity_statistics":eq,
                "failures":failures,"technical_error":None if error is None else f"{type(error).__name__}: {error}"}
            combined = [*attempts,attempt]
            save(attempts_path,combined)
            totals = {key:sum(x["equity_statistics"][key] for x in combined) for key in ("input_snapshots","candidate_runs","benchmark_runs")}
            totals["account_timings"] = [t for x in combined for t in x["equity_statistics"]["account_timings"]]
            save(WORK/"others/execution.json",{**attempt,"equity_statistics":totals,
                "total_seconds":sum(x["total_seconds"] for x in combined),"attempt_count":len(combined),
                "imported_observations":81,"new_proposals":len(history),"unique_used_configurations":len(measured),
                "prior_reused_configurations":sum(x["provenance"]["kind"]=="PRIOR_REUSE" for x in measured.values()),
                "within_new_proposal_duplicates":sum(x.get("duplicate",False) for x in history),
                "status":"COMPLETE" if error is None and len(history)==48 else "STOPPED", "manifest":manifest})
    assert len(history)==48 and all(x["state"]=="COMPLETE" for x in history)
    print("JOINT_SEARCH_COMPLETE",len(history),len(measured),flush=True)


if __name__ == "__main__":
    assert set(sys.argv[1:]) <= {WORK.name,"--preflight"}
    main("--preflight" in sys.argv[1:])
