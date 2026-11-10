"""Replay the frozen S018-v1 behavior as an explicit S019 comparison reference."""
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / ".tmp/s019-reference"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TEMP_ROOT), TMP=str(TEMP_ROOT), PYTHONDONTWRITEBYTECODE="1",
    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
sys.dont_write_bytecode = True

from czsc_trader.application import RepositoryContext, publish_evidence  # noqa: E402
from czsc_trader.research_tools import (  # noqa: E402
    EquityBuyHold, EquityEvaluationRequest, EquitySources, EvaluationBenchmark,
    EvaluationEvidenceWrite, EvidenceRef, ExperimentRef, ResearchExecutionSession,
)
from czsc_trader.research_tools.equity_replay import materialize_equity  # noqa: E402
from dataflows import TimeInterval  # noqa: E402
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash  # noqa: E402
from data_window import HISTORY_START, SOURCE, replay_context, save  # noqa: E402


def candidate():
    release = ROOT / "strategies/S018/releases/v1"
    manifest = json.loads((release / "release_manifest.json").read_text(encoding="utf-8"))
    expected = "80a7ca699f5814ad3e9162de1828d9848b5a0e7077857eb92002aec10c3f631e"
    if manifest["strategy_version_hash"] != expected or manifest["runtime_candidate_id"] != "C9397":
        raise ValueError("Frozen reference changed since mandate confirmation")
    for name, digest in manifest["files"].items():
        assert sha256((release / name).read_bytes()).hexdigest() == digest
    frozen = json.loads((ROOT / "strategies/S018/versions/v1.json").read_text(encoding="utf-8"))
    definition = frozen["strategy_payload"]["equity_definition"]
    original = json.loads(json.dumps(definition))
    source_root = WORK / "src/reference"
    source_root.mkdir(exist_ok=True)
    for name in definition["source_files"]:
        (source_root / name).write_bytes((release / manifest["runtime_root"] / name).read_bytes())
    assert equity_source_hash(source_root, tuple(definition["source_files"])) == definition["source_sha256"]
    for item in definition["auxiliary_inputs"]:
        item["source"] = {"provider": SOURCE.provider, "revision": SOURCE.revision}
    ref = EquityStrategyCandidate("S019", "C0001", EquityStrategyDefinition.from_dict(definition), source_root)
    save("reference_identity.json", {"purpose": "FIXED_S018_V1_COMPARISON_ONLY", "origin": manifest,
        "reference_identity": ref.to_dict() if hasattr(ref, "to_dict") else {"strategy_id": "S019", "candidate_id": "C0001"},
        "original_definition": original, "evaluation_definition": definition,
        "adaptations": ["research batch/candidate identity", "auxiliary source revision"],
        "strategy_source_and_financial_parameters": "UNCHANGED"})
    return ref


def summarize():
    reference = EvidenceRef.from_dict(json.loads((WORK / "others/reference_account.json").read_text(encoding="utf-8")))
    path = reference.resolve(ROOT)

    def resolve(item):
        content = path.with_name(item["sha256"] + ".json").read_bytes()
        assert sha256(content).hexdigest() == item["sha256"]
        return content

    payload = materialize_equity(path.read_bytes(), resolve).payload
    summary = {}
    for name, run in payload["runs"].items():
        metrics = run["metrics"]
        counts = metrics["rolling_60_closed_cycle_counts"]
        drawdown = metrics["daily_max_drawdown"]
        assert metrics["sessions"] == 1212 and len(counts) == 1153
        daily = run["account_daily"]
        yearly, previous = {}, 100000.0
        for year in (2022, 2023, 2024, 2025, 2026):
            group = [row for row in daily if row["session"].startswith(str(year))]
            yearly[str(year)] = group[-1]["equity"] / previous - 1
            previous = group[-1]["equity"]
        summary[name] = {"nar": metrics["annualized_return"], "drawdown": drawdown,
            "calmar": metrics["annualized_return"] / drawdown if drawdown > 1e-12 else None,
            "total_return": metrics["total_return"], "closed_cycles": metrics["closed_cycles"],
            "frequency_median": metrics["rolling_60_closed_cycle_median"],
            "frequency_coverage": sum(x >= 3 for x in counts) / len(counts), "frequency_windows": len(counts),
            "account_days": len(daily), "year_returns": yearly}
    save("reference_summary.json", {"account": reference.to_dict(), "runs": summary,
        "basis": "Cold-read published V4 ledger; no new replay for summarization."})
    print(json.dumps(summary), flush=True)


def main():
    if (WORK / "others/reference_account.json").exists():
        summarize()
        return
    fixed = candidate()
    repository = RepositoryContext.discover(ROOT)
    experiment = ExperimentRef("S019", WORK.name)
    context = replay_context(repository, fixed.definition.execution_spec)
    zone = ZoneInfo("America/New_York")
    request = EquityEvaluationRequest(experiment, fixed,
        TimeInterval(datetime(2022, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone)),
        HISTORY_START, EquitySources(SOURCE, SOURCE, SOURCE), 100000.0, 0.001,
        benchmark=EvaluationBenchmark(EquityBuyHold(fixed.definition.execution_spec)),
        drawdown_basis="SESSION_CLOSE", concentration_basis="MAX_SINGLE")
    started = perf_counter()
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        save("reference_input_binding.json", prepared.request.input_binding.to_dict())
        print("PREPARED_REFERENCE", flush=True)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        if outcome.result is None:
            save("reference_failure.json", {"status": outcome.status.value, "error": str(outcome.error)})
            raise RuntimeError(outcome.error)
        ref = publish_evidence(context, EvaluationEvidenceWrite(experiment, "fixed-s018-v1-reference", prepared, outcome.result), execution=execution)
        save("reference_account.json", ref.to_dict())
        save("replay_execution.json", {"seconds": perf_counter() - started, "published_account": ref.to_dict()})
    summarize()


if __name__ == "__main__":
    main()
