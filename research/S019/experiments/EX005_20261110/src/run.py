"""Evaluate the four predeclared structures with public TDR account replay."""
from datetime import datetime
from dataclasses import asdict
from hashlib import sha256
import json
import faulthandler
import os
from pathlib import Path
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
TEMP = ROOT / ".tmp/s019-prototypes"
TEMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TEMP), TMP=str(TEMP), PYTHONDONTWRITEBYTECODE="1",
    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
sys.dont_write_bytecode = True
if __name__ == "__mp_main__":
    sys.stderr = (TEMP / f"worker-{os.getpid()}.err.log").open("w", encoding="utf-8")
    faulthandler.enable(file=sys.stderr)
    print("worker startup", os.getpid(), file=sys.stderr, flush=True)
sys.path.insert(0, str(WORK.parent / "EX003_20261110/src"))

from czsc_trader.application import RepositoryContext, publish_evidence  # noqa: E402
from czsc_trader.research_tools import (  # noqa: E402
    EquityBuyHold, EquityEvaluationRequest, EquitySources, EvaluationBenchmark,
    EvaluationEvidenceWrite, EvidenceRef, ExperimentRef, ResearchExecutionSession,
)
from czsc_trader.research_tools.equity_replay import materialize_equity  # noqa: E402
from dataflows import BarFrequency, TimeInterval  # noqa: E402
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, ExecutionResources, equity_source_hash  # noqa: E402
from data_window import HISTORY_START, SOURCE, replay_context  # noqa: E402
if __name__ == "__mp_main__":
    print("worker imports complete", os.getpid(), file=sys.stderr, flush=True)

MODES = ("all", "common", "trend_filter", "adaptive_exit")


def save(name, value):
    (WORK / "others" / name).write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def progress(value):
    print("PROGRESS", value, flush=True)


def candidates():
    base = json.loads((WORK.parent / "EX003_20261110/others/reference_identity.json").read_text(encoding="utf-8"))["evaluation_definition"]
    base.update(source_sha256=equity_source_hash(WORK / "src", ("strategy.py",)), warmup_bars=2, session_context=True,
        parameter_schema_json=json.dumps({"mode": {"type": "string", "enum": list(MODES)}}),
        state_schema={"account_fields": [], "cycle_fields": [{"key": "uptrend", "value_type": "bool", "nullable": False}]})
    base["execution_spec"]["decision_clock"] = BarFrequency.M30.value
    sector = base["auxiliary_inputs"][0]
    sector.update(name="soxx_daily", warmup_bars=65)
    mu = {**sector, "name": "mu_daily", "instrument": base["instrument"]}
    base["auxiliary_inputs"] = [mu, sector]
    found = []
    for i, mode in enumerate(MODES, 6):
        definition = {**base, "parameters_json": json.dumps({"mode": mode})}
        candidate = EquityStrategyCandidate("S019", f"C{i:04d}", EquityStrategyDefinition.from_dict(definition), WORK / "src")
        save(f"{mode}_definition.json", candidate.definition.to_dict())
        found.append(candidate)
    return found


def summarize():
    summaries = {}
    for mode in MODES:
        ref = EvidenceRef.from_dict(json.loads((WORK / f"others/{mode}_account.json").read_text(encoding="utf-8")))
        path = ref.resolve(ROOT)

        def resolve(item):
            content = path.with_name(item["sha256"] + ".json").read_bytes()
            assert sha256(content).hexdigest() == item["sha256"]
            return content

        payload = materialize_equity(path.read_bytes(), resolve).payload
        rows = {}
        for name, run in payload["runs"].items():
            metrics = run["metrics"]
            counts = metrics["rolling_60_closed_cycle_counts"]
            dd, nar = metrics["daily_max_drawdown"], metrics["annualized_return"]
            assert metrics["sessions"] == 1212 and len(counts) == 1153
            years, previous = {}, 100000.0
            for year in (2022, 2023, 2024, 2025, 2026):
                daily = [row for row in run["account_daily"] if row["session"].startswith(str(year))]
                years[str(year)] = daily[-1]["equity"] / previous - 1
                previous = daily[-1]["equity"]
            rows[name] = {"nar": nar, "drawdown": dd, "calmar": nar / dd if dd > 1e-12 else None,
                "closed_cycles": metrics["closed_cycles"], "frequency_median": metrics["rolling_60_closed_cycle_median"],
                "frequency_coverage": sum(x >= 3 for x in counts) / len(counts), "year_returns": years}
        summaries[mode] = {"account": ref.to_dict(), "runs": rows}
    save("summary.json", summaries)
    print(json.dumps(summaries, ensure_ascii=False), flush=True)


def main():
    diagnostic = "--diagnostic" in sys.argv
    found = candidates()
    pending = [(mode, candidate) for mode, candidate in zip(MODES, found, strict=True)
               if not (WORK / f"others/{mode}_account.json").exists()]
    if not pending:
        summarize()
        return
    if diagnostic:
        pending = pending[:1]
    context = replay_context(RepositoryContext.discover(ROOT), found[0].definition.execution_spec)
    workers = 1 if diagnostic else 4
    context.evaluation.resources = ExecutionResources(workers, 1, 19)
    experiment = ExperimentRef("S019", WORK.name)
    zone = ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2022, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone))
    started = perf_counter()
    with ResearchExecutionSession(context, experiment=experiment, on_progress=progress) as execution:
        prepared = []
        for mode, candidate in pending:
            request = EquityEvaluationRequest(experiment, candidate, window, HISTORY_START,
                EquitySources(SOURCE, SOURCE, SOURCE), 100000.0, .001,
                benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),
                drawdown_basis="SESSION_CLOSE", concentration_basis="MAX_SINGLE")
            item = context.evaluation.prepare(request, execution=execution)
            save(f"{mode}_binding.json", item.request.input_binding.to_dict())
            prepared.append(item)
        print("PREPARED", len(prepared), flush=True)
        preparation_seconds = perf_counter() - started
        outcomes = context.evaluation.evaluate_many(tuple(prepared), execution=execution)
        save("runtime_statistics.json", {"execution": asdict(execution.stats), "equity": asdict(execution.equity_statistics)})
        evaluation_seconds = perf_counter() - started - preparation_seconds
        failures = []
        for (mode, _), item, outcome in zip(pending, prepared, outcomes, strict=True):
            if outcome.result is None:
                failure = {"mode": mode, "status": outcome.status.value, "error": str(outcome.error)}
                failures.append(failure)
                save(f"{mode}_failure.json", failure)
            else:
                ref = publish_evidence(context, EvaluationEvidenceWrite(experiment, f"prototype-{mode}", item, outcome.result), execution=execution)
                save(f"{mode}_account.json", ref.to_dict())
                print("PUBLISHED", mode, ref.sha256, flush=True)
        save("diagnostic_execution.json" if diagnostic else "execution.json", {"max_workers": workers, "native_threads": 1, "requested": [mode for mode, _ in pending],
            "preparation_seconds": preparation_seconds, "evaluation_seconds": evaluation_seconds,
            "total_seconds": perf_counter() - started, "failures": failures})
        if failures:
            raise RuntimeError(failures)
    if not diagnostic:
        summarize()


if __name__ == "__main__":
    main()
