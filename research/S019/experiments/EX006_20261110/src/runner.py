"""Shared public-TDR execution, evidence reading and publication for ten rounds."""
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
OWNER = Path(__file__).resolve().parents[1]
TEMP = ROOT / ".tmp/s019-ten-rounds"
TEMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TEMP), TMP=str(TEMP), PYTHONDONTWRITEBYTECODE="1",
    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
sys.dont_write_bytecode = True
sys.path.insert(0, str(OWNER.parent / "EX003_20261110/src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from czsc_trader.application import (  # noqa: E402
    RepositoryContext, create_research_context, publish_evidence, validate_experiment,
)
from czsc_trader.research_tools.equity_replay import materialize_equity  # noqa: E402
from dataflows import TimeInterval, ProviderConfig  # noqa: E402
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash  # noqa: E402
from data_window import HISTORY_START, SOURCE, replay_context  # noqa: E402


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def read_account(path):
    ref = d.EvidenceRef.from_dict(json.loads(path.read_text(encoding="utf-8")))
    source = ref.resolve(ROOT)
    content = source.read_bytes()
    assert sha256(content).hexdigest() == ref.sha256

    def resolve(item):
        data = source.with_name(item["sha256"] + ".json").read_bytes()
        assert sha256(data).hexdigest() == item["sha256"]
        return data

    return ref, materialize_equity(content, resolve).payload


def metrics(run, benchmark_dd):
    m = run["metrics"]
    dd, nar = m["daily_max_drawdown"], m["annualized_return"]
    counts = m["rolling_60_closed_cycle_counts"]
    assert m["sessions"] == 1212 and len(counts) == 1153
    calmar = nar / dd if dd > 1e-12 else None
    coverage = sum(x >= 3 for x in counts) / len(counts)
    years, previous = {}, 100000.0
    for year in (2022, 2023, 2024, 2025, 2026):
        daily = [row for row in run["account_daily"] if row["session"].startswith(str(year))]
        years[str(year)] = daily[-1]["equity"] / previous - 1
        previous = daily[-1]["equity"]
    gates = {"nar": nar >= .55, "calmar": calmar is not None and calmar >= 5,
        "absolute_dd": dd <= .25, "relative_dd": dd <= .8 * benchmark_dd,
        "frequency_median": m["rolling_60_closed_cycle_median"] >= 6, "frequency_coverage": coverage >= .9}
    return {"nar": nar, "drawdown": dd, "bar_drawdown": m["bar_max_drawdown"], "calmar": calmar,
        "closed_cycles": m["closed_cycles"], "frequency_median": m["rolling_60_closed_cycle_median"],
        "frequency_coverage": coverage, "year_returns": years, "gates": gates, "eligible": all(gates.values()),
        "fees": float(sum(row["fees"] for row in run["fills"]))}


def rolling_metrics(daily, start):
    base = 100000.0 if start == 0 else daily[start - 1]["equity"]
    values = np.array([base, *(x["equity"] for x in daily[start:start + 252])])
    nar, dd = float(values[-1] / base - 1), float(np.max(1 - values / np.maximum.accumulate(values)))
    return {"nar": nar, "calmar": nar / dd if dd > 1e-12 else None, "drawdown": dd}


def summarize(work, config):
    _, fixed = read_account(OWNER.parent / "EX003_20261110/others/reference_account.json")
    summaries, diagnostics = {}, {}
    for row in config["candidates"]:
        name = row["name"]
        ref, payload = read_account(work / f"others/{name}_account.json")
        expected = json.loads((work / f"others/{name}_definition.json").read_text(encoding="utf-8"))
        assert expected["source_sha256"] == equity_source_hash(work / "src", tuple(expected["source_files"]))
        run, bh = payload["runs"]["candidate"], payload["runs"]["buy_hold"]
        for decision in run["decisions"]:
            assert pd.Timestamp(decision["observed_through"]) <= pd.Timestamp(decision["decision_at"]) <= pd.Timestamp(decision["execution_start"])
            assert 0 <= decision["target"] <= 1
        assert all(x["cash"] >= -1e-8 and x["quantity"] >= 0 for x in run["account_points"])
        assert all(x["quantity"] > 0 and x["quantity"] == int(x["quantity"]) for x in run["fills"])
        bh_dd = bh["metrics"]["daily_max_drawdown"]
        summaries[name] = {"id": row["id"], "parameters": row["parameters"], "account": ref.to_dict(),
            "candidate": metrics(run, bh_dd), "buy_hold": metrics(bh, bh_dd),
            "audit": {"chronology": "PASS", "cash_longonly_integer": "PASS", "source_hash": "PASS"}}
        examples = []
        seen = set()
        for decision in run["decisions"]:
            reason = decision["explanation"]["judgment"]
            if reason not in seen:
                seen.add(reason)
                examples.append(decision)
        windows, streak, longest = [], {}, {}
        for start in range(0, 1212 - 251, 21):
            values = {label: rolling_metrics(account["account_daily"], start) for label, account in
                (("candidate", run), ("buy_hold", bh), ("S018_v1", fixed["runs"]["candidate"]))}
            delta = {}
            for baseline in ("buy_hold", "S018_v1"):
                for metric in ("nar", "calmar"):
                    key = baseline + "_" + metric
                    a, b = values["candidate"][metric], values[baseline][metric]
                    delta[key] = a - b if a is not None and b is not None else None
                    streak[key] = streak.get(key, 0) + 1 if delta[key] is not None and delta[key] < 0 else 0
                    longest[key] = max(longest.get(key, 0), streak[key])
            windows.append({"start": run["account_daily"][start]["session"], "end": run["account_daily"][start + 251]["session"],
                "metrics": values, "differences": delta, "consecutive_underperformance": dict(streak)})
        diagnostics[name] = {"examples": examples, "rolling252": windows, "longest_underperformance": longest}
        print(name, row["id"], json.dumps(summaries[name]["candidate"]), flush=True)
    save(work / "others/summary.json", summaries)
    save(work / "others/diagnostics.json", diagnostics)


def run(work, config):
    base = json.loads((OWNER.parent / "EX005_20261110/others/common_definition.json").read_text(encoding="utf-8"))
    base.update(source_sha256=equity_source_hash(work / "src", ("strategy.py",)),
        state_schema=config.get("state_schema", base["state_schema"]))
    for aux in base["auxiliary_inputs"]:
        aux["warmup_bars"] = config.get("daily_warmup", 65)
    base["warmup_bars"] = config.get("primary_warmup", 2)
    candidates = []
    for row in config["candidates"]:
        parameters = row["parameters"]
        schema = {key: {"type": "boolean" if type(value) is bool else "integer" if type(value) is int
            else "number" if type(value) is float else "string"} for key, value in parameters.items()}
        definition = EquityStrategyDefinition.from_dict({**base, "parameters_json": json.dumps(parameters),
            "parameter_schema_json": json.dumps(schema)})
        candidate = EquityStrategyCandidate("S019", row["id"], definition, work / "src")
        path = work / f"others/{row['name']}_definition.json"
        if path.exists():
            assert json.loads(path.read_text(encoding="utf-8")) == definition.to_dict(), "Existing prototype identity changed"
        else:
            save(path, definition.to_dict())
        candidates.append(candidate)
    pending = [(row, candidate) for row, candidate in zip(config["candidates"], candidates, strict=True)
        if not (work / f"others/{row['name']}_account.json").exists()]
    if pending:
        context = replay_context(RepositoryContext.discover(ROOT), candidates[0].definition.execution_spec)
        experiment = d.ExperimentRef("S019", work.name)
        zone = ZoneInfo("America/New_York")
        window = TimeInterval(datetime(2022, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone))
        started = perf_counter()
        with d.ResearchExecutionSession(context, experiment=experiment,
                on_progress=lambda value: print(value, flush=True)) as execution:
            prepared = []
            for row, candidate in pending:
                request = d.EquityEvaluationRequest(experiment, candidate, window, HISTORY_START,
                    d.EquitySources(SOURCE, SOURCE, SOURCE), 100000.0, config.get("fee_rate", .001),
                    benchmark=d.EvaluationBenchmark(d.EquityBuyHold(candidate.definition.execution_spec)),
                    drawdown_basis="SESSION_CLOSE", concentration_basis="MAX_SINGLE")
                item = context.evaluation.prepare(request, execution=execution)
                save(work / f"others/{row['name']}_binding.json", item.request.input_binding.to_dict())
                prepared.append(item)
            print("PREPARED", len(prepared), flush=True)
            prepare_seconds = perf_counter() - started
            outcomes = context.evaluation.evaluate_many(tuple(prepared), execution=execution)
            compute_seconds = perf_counter() - started - prepare_seconds
            failures = []
            for (row, _), item, outcome in zip(pending, prepared, outcomes, strict=True):
                if outcome.result is None:
                    failures.append({"name": row["name"], "status": outcome.status.value, "error": str(outcome.error)})
                    continue
                ref = publish_evidence(context, d.EvaluationEvidenceWrite(experiment, row["name"], item, outcome.result), execution=execution)
                save(work / f"others/{row['name']}_account.json", ref.to_dict())
            save(work / "others/execution.json", {"resources": {"workers": 4, "native_threads": 1},
                "prepare_seconds": prepare_seconds, "evaluate_seconds": compute_seconds, "total_seconds": perf_counter() - started,
                "statistics": asdict(execution.stats), "equity_statistics": asdict(execution.equity_statistics), "failures": failures})
            if failures:
                raise RuntimeError(failures)
    summarize(work, config)


def publish(work, config):
    repo = RepositoryContext.discover(ROOT)
    context = create_research_context(repo, d.ResearchBatchRef("S019"), providers=ProviderConfig(bindings={}, equity_bindings={}))
    experiment = d.ExperimentRef("S019", work.name)
    evidence = [d.EvidenceRef.from_dict(json.loads((work / f"others/{row['name']}_account.json").read_text(encoding="utf-8")))
        for row in config["candidates"]]
    evidence.extend(d.EvidenceRef.from_dict(json.loads((ROOT / path).read_text(encoding="utf-8"))) for path in config.get("controls", []))
    paths = [*sorted((work / "src").glob("*.py")), *sorted((work / "protocols").glob("*")),
        *sorted((work / "others").glob("*.json")), OWNER / "src/runner.py",
        OWNER.parent / "EX003_20261110/src/data_window.py", OWNER.parent / "EX003_20261110/others/preparation.json",
        OWNER.parent / "EX001_20261110/src/load_data.py", OWNER.parent / "EX001_20261110/src/prepare_data.py"]
    for i, path in enumerate(dict.fromkeys(paths)):
        if path.name == "publication.json":
            continue
        ext = path.suffix[1:]
        mime = {"py": "text/x-python", "md": "text/markdown", "json": "application/json"}[ext]
        evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(experiment, f"material-{i:02d}-{path.stem}", path.read_bytes(), mime, ext)))
    pointer = work / "report_ref.json"
    previous = d.EvidenceRef.from_dict(json.loads(pointer.read_text(encoding="utf-8"))["report"]) if pointer.exists() else None
    ref = publish_evidence(context, d.ExperimentReportWrite(experiment, sha256((work / "report.md").read_bytes()).hexdigest(),
        d.ExperimentOutcome.COMPLETED, tuple(evidence), previous=previous))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(experiment, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    save(work / "others/publication.json", {"report": ref.to_dict(), "validation": validation.to_dict()})
    print("REPORT", validation.status.value, ref.sha256, flush=True)


if __name__ == "__main__":
    work = ROOT / "research/S019/experiments" / sys.argv[2]
    config = json.loads((work / "protocols/config.json").read_text(encoding="utf-8"))
    {"run": run, "publish": publish, "summarize": summarize}[sys.argv[1]](work, config)
