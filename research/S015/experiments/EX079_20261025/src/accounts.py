"""Public complete-account comparisons for prospectively declared process prototypes."""
# ruff: noqa: E402

import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
import importlib.util
import json
from pathlib import Path
import pandas as pd
import optuna
from czsc_trader.application import (
    RepositoryContext,
    create_research_context,
    publish_evidence,
    open_research_execution,
)
from czsc_trader.research_tools import (
    ResearchBatchRef,
    ExperimentRef,
    ExecutionResources,
    EvidenceRef,
    MaterialEvidenceWrite,
    EvaluationRequest,
    EvaluationWindow,
    EvaluationCost,
    EvaluationBenchmark,
    LimitBuyHold,
    EvaluationEvidenceWrite,
)
from strategy_runtime import StrategyCandidate, implementation_sha256

HOME = Path(__file__).resolve().parents[1]
ROOT = HOME.parents[3]
BASE = HOME.parent
SOURCE = BASE / "EX076_20261024/src/strategy_runtime"
FILES = ["strategies/price_process.py"]


def read(p):
    return json.loads(p.read_bytes())


def plain(v):
    if isinstance(v, Mapping):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    return v


def save(p, v):
    p.write_text(
        json.dumps(plain(v), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def context(workers=8):
    return create_research_context(
        RepositoryContext.discover(ROOT),
        ResearchBatchRef("S015"),
        resources=ExecutionResources(workers, 1, 13),
    )


def module(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def material(ctx, ex, p):
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            ex,
            p.stem,
            p.read_bytes(),
            {
                ".py": "text/x-python",
                ".json": "application/json",
                ".csv": "text/csv",
                ".md": "text/markdown",
            }[p.suffix],
            p.suffix[1:],
        ),
    )


def candidate(ex, index, p):
    return StrategyCandidate(
        "S015",
        read(ex.resolve(ROOT) / "protocols/accounts.json")["candidate_ids"][index],
        {
            "decision_feedback": "MARKET_INTENT",
            "parameters": p,
            "runtime": {
                "module": "strategy_runtime.strategies.price_process",
                "qualname": "PriceProcess",
                "contract_version": 2,
                "source_files": FILES,
                "source_sha256": implementation_sha256(FILES, source_root=SOURCE),
            },
        },
        SOURCE,
    )


def request(ctx, ex, index, p):
    c = candidate(ex, index, p)
    return ctx.evaluation.prepare(
        EvaluationRequest(
            ROOT,
            ex.experiment_id,
            c,
            {
                "candidate_id": c.reference_id,
                "source_files": FILES,
                "implementation_sha256": c.payload["runtime"]["source_sha256"],
            },
            "159326.SZ",
            "etf",
            (
                EvaluationWindow("full", date(2025, 1, 2), date(2026, 10, 21)),
                EvaluationWindow("s011_common", date(2025, 2, 6), date(2026, 10, 21)),
            ),
            date(2026, 10, 21),
            100000.0,
            (EvaluationCost("fee_x2", 0.002, "STRESS"),),
            benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.01, 0.001, 0.1, 1000000)),
        )
    )


def prepare(ex):
    here = ex.resolve(ROOT)
    assert not (here / "others/protocol_refs.json").exists()
    ctx = context(1)
    proto = read(here / "protocols/accounts.json")
    assert proto["round"] <= 20
    summary_ref = EvidenceRef.from_dict(
        read(BASE / "EX033_20261023/others/results.json")["summary_source"]
    )
    assert (
        summary_ref.resolve(ROOT).read_bytes()
        == (BASE / "EX016_20261023/src/suite.py").read_bytes()
    )
    proto["summary_source"] = summary_ref.to_dict()
    save(here / "protocols/accounts.json", proto)
    refs = {
        str(p.relative_to(ROOT)): material(ctx, ex, p).to_dict()
        for p in (here / "protocols/accounts.json", Path(__file__), SOURCE / FILES[0])
    }
    save(here / "others/protocol_refs.json", refs)
    print("ACCOUNT_PROTOCOL_PUBLISHED", ex.experiment_id, flush=True)


def run(ex, serial=False):
    here = ex.resolve(ROOT)
    assert not (here / "others/results.json").exists()
    for key, ref in read(here / "others/protocol_refs.json").items():
        assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes() == (ROOT / key).read_bytes()
    proto = read(here / "protocols/accounts.json")
    sr = EvidenceRef.from_dict(proto["summary_source"])
    assert sr.resolve(ROOT).read_bytes() == (BASE / "EX016_20261023/src/suite.py").read_bytes()
    suite = module(BASE / "EX016_20261023/src/suite.py", "authenticated_summary")
    ctx = context()
    configs = proto["configurations"]
    requests = [request(ctx, ex, i, p) for i, p in enumerate(configs)]
    study = optuna.create_study(
        directions=["maximize", "minimize", "maximize", "minimize"],
        sampler=optuna.samplers.RandomSampler(seed=13),
    )
    for i in range(len(configs)):
        study.enqueue_trial({"configuration_index": i})
    trials = []
    for i in range(len(configs)):
        trial = study.ask()
        assert trial.suggest_int("configuration_index", 0, len(configs) - 1) == i
        trials.append(trial)
    print("ACCOUNTS_PREPARED", ex.experiment_id, len(requests), flush=True)
    pre = None
    pre_ref = None
    if serial:
        pre = context(1).evaluation.evaluate(requests[0])
        pre_ref = publish_evidence(
            ctx, EvaluationEvidenceWrite(ex, "serial_control", requests[0], pre)
        )
        save(
            here / "others/serial_check.json",
            {"evidence": pre_ref.to_dict(), "result_hash": pre.result_hash},
        )
        print("SERIAL_PREFLIGHT", flush=True)
    rows = []
    with open_research_execution(ctx, experiment=ex) as session:
        for start in range(0, len(requests), 8):
            block = requests[start : start + 8]
            outs = ctx.evaluation.evaluate_many(tuple(block), execution=session)
            for offset, (req, out) in enumerate(zip(block, outs, strict=True)):
                if out.status.value != "SUCCEEDED":
                    save(
                        here / "others/technical_failure.json",
                        {
                            "candidate": req.strategy.candidate_id,
                            "error": str(out.error),
                            "completed": len(rows),
                        },
                    )
                    raise RuntimeError(out.error)
                result = out.result
                if pre is not None and start + offset == 0:
                    assert result.result_hash == pre.result_hash
                    for a, b in zip(result.runs, pre.runs, strict=True):
                        for name in ("account_daily", "decisions", "orders", "fills", "trades"):
                            pd.testing.assert_frame_equal(
                                getattr(a.execution, name), getattr(b.execution, name)
                            )
                row = suite.summary(req, result)
                ref = publish_evidence(
                    ctx, EvaluationEvidenceWrite(ex, req.strategy.candidate_id, req, result)
                )
                row["evidence"] = ref.to_dict()
                row["identity"] = {
                    "key": result.runs[0].identity.candidate.to_dict(),
                    "content_sha256": result.runs[0].identity.content_sha256,
                }
                save(
                    here / f"others/{req.strategy.candidate_id}_payload.json",
                    plain(req.strategy.payload),
                )
                row["dependencies"] = [asdict(x) for x in req.dependencies]
                row["years"] = []
                for run0 in result.runs:
                    a = run0.execution.account_daily
                    for name in ("account_daily", "decisions", "orders", "fills", "trades"):
                        getattr(run0.execution, name).to_csv(
                            here
                            / f"others/{req.strategy.candidate_id}_{run0.window_id}_{name}.csv",
                            index=False,
                        )
                    previous = 100000.0
                    for year, part in a.groupby(pd.to_datetime(a.date).dt.year, sort=True):
                        row["years"].append(
                            {
                                "window": run0.window_id,
                                "year": int(year),
                                "net_return": float(part.equity.iloc[-1] / previous - 1),
                            }
                        )
                        previous = float(part.equity.iloc[-1])
                values = [
                    row["runs"][w][m] for w in ("full", "s011_common") for m in ("net_return", "dd")
                ]
                study.tell(trials[start + offset], values)
                rows.append(row)
                save(
                    here / "others/progress.json",
                    {"rows": rows, "completed": len(rows), "total": len(requests)},
                )
                print(
                    row["candidate_id"],
                    plain(row["parameters"]),
                    {
                        w: {
                            k: r[k]
                            for k in (
                                "net_return",
                                "dd",
                                "closed",
                                "frequency_median",
                                "frequency_good",
                            )
                        }
                        for w, r in row["runs"].items()
                    },
                    flush=True,
                )
    save(
        here / "others/results.json",
        {
            "rows": rows,
            "new_configurations": 0,
            "reused_candidate_identities": len(rows),
            "formal_accounts": 2 * len(rows),
            "technical_accounts": 2 if serial else 0,
            "serial_equal": serial,
            "summary_source": sr.to_dict(),
            "serial_ref": pre_ref.to_dict() if pre_ref else None,
            "execution_stats": asdict(session.stats),
            "center_pass_count": sum(r["both_center_pass"] for r in rows),
            "optuna": [
                {"number": t.number, "params": t.params, "values": t.values, "state": str(t.state)}
                for t in study.trials
            ],
        },
    )
    print("ACCOUNTS_COMPLETE", ex.experiment_id, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "run", "precheck"))
    parser.add_argument("--experiment", default=HOME.name)
    a = parser.parse_args()
    ex = ExperimentRef("S015", a.experiment)
    if a.mode == "prepare":
        prepare(ex)
    else:
        run(ex, a.mode == "precheck")
