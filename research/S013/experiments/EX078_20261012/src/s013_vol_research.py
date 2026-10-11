"""One S013-only fixed component study, with immutable prospective publication."""

from datetime import date, datetime, timezone
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-vol-concentration"
OUT = ROOT / ".tmp/s013-vol-concentration-result"
sys.path.insert(0, str(WORK))
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX071_20261011/src"))
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX058_20261011/src"))
common = importlib.import_module("common")


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013 only")
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError("Immutable evidence hash mismatch")
    return path


def put(ctx, exp, path):
    path = Path(path)
    media = {".py": "text/x-python", ".csv": "text/csv", ".md": "text/markdown"}.get(
        path.suffix, "application/json"
    )
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            exp, "vol-" + path.stem.replace("_", "-"), path.read_bytes(), media, path.suffix[1:]
        ),
    ).to_dict()


def frame(path):
    import pandas as pd

    result = pd.read_csv(path, index_col="signal_date", float_precision="round_trip")
    result.index = pd.to_datetime(result.index).as_unit("ns")
    return result


def check(plan):
    for name, expected in plan["source_files"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Source identity changed: " + name)
    for name, expected in plan["native_cache"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Cache identity changed: " + name)
    for ref in plan["input_references"].values():
        public(ref)


def declare():
    prospective = read(WORK / "prospective.json")
    check(prospective)
    if read(WORK / "focused_checks.json")["status"] != "PASS":
        raise ValueError("Focused checks must pass")
    ctx = common.context(1)
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "持仓中的四日波动集中与退出机会成本",
            "固定四日/二十日Close波动比能否在24项已知状态控制后增加h4持有风险与继续收益信息？",
            date(2026, 10, 12),
        ),
    )
    plan = {
        **prospective,
        "experiment": exp.to_dict(),
        "declared_utc": datetime.now(timezone.utc).isoformat(),
    }
    write(OUT / "plan.json", plan)
    write(OUT / "experiment.json", exp.to_dict())
    refs = {
        "plan.json": put(ctx, exp, OUT / "plan.json"),
        "focused_checks.json": put(ctx, exp, WORK / "focused_checks.json"),
    }
    src = exp.resolve(ROOT) / "src"
    src.mkdir(exist_ok=True)
    for name in plan["source_files"]:
        path = ROOT / name
        refs[name] = put(ctx, exp, path)
        # Preserve only new sources locally; old immutable sources stay referenced.
        if path.is_relative_to(ROOT / ".tmp"):
            target = src / path.name
            if target.exists():
                raise ValueError("Source basename collision")
            target.write_bytes(path.read_bytes())
    write(exp.resolve(ROOT) / "protocols/plan.json", plan)
    write(exp.resolve(ROOT) / "protocols/method_references.json", refs)
    print(
        {"experiment": exp.experiment_id, "prospective_published": True, "new_accounts": 0},
        flush=True,
    )


def study():
    plan = read(OUT / "plan.json")
    check(plan)
    exp = ExperimentRef.from_dict(plan["experiment"])
    refs = read(exp.resolve(ROOT) / "protocols/method_references.json")
    if read(public(refs["plan.json"])) != plan:
        raise ValueError("Published prospective binding changed")
    write(
        OUT / "study_attempt.json",
        {"status": "STARTED", "plan_sha256": digest(OUT / "plan.json"), "new_accounts": 0},
    )
    try:
        bound, result = common.cache_read(ROOT / ".tmp/s013-mechanism-EX058/N0.pkl.gz")
        if serialize_evaluation_evidence(bound, result) != read(
            public(plan["input_references"]["native"])
        ):
            raise ValueError("Full original native account identity mismatch")
        if bound.symbol != "510500.SH" or bound.strategy.candidate_id != "C8880":
            raise ValueError("Original C8880 only")
        assembler = importlib.import_module("inputs")
        statistics = importlib.import_module("vol_statistics")
        features, labels, scopes, state, prices, proof = assembler.construct(
            frame(public(plan["input_references"]["old_features"])),
            frame(public(plan["input_references"]["warm_prices"])),
            bound,
            result,
        )
        if common.SOURCE_CALLS:
            raise ValueError("Provider calls forbidden")
        for name, value in {
            "features.csv": features,
            "labels.csv": labels,
            "scopes.csv": scopes,
            "known_state.csv": state,
            "prices.csv": prices,
        }.items():
            with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
                value.to_csv(stream, index_label="signal_date", float_format="%.17g")
        write(
            OUT / "input_checks.json",
            {
                **proof,
                "native_exact": True,
                "input_references": plan["input_references"],
                "provider_calls": 0,
                "new_accounts": 0,
            },
        )
        outcome = statistics.analyze(features, labels, scopes)
        write(OUT / "statistics.json", outcome)
        write(
            OUT / "study_complete.json",
            {
                "status": "COMPLETE",
                "analyze_calls": 1,
                "statistics_sha256": digest(OUT / "statistics.json"),
                "new_accounts": 0,
                "provider_calls": 0,
            },
        )
        ctx = common.context(1)
        result_refs = {
            name: put(ctx, exp, OUT / name)
            for name in (
                "input_checks.json",
                "features.csv",
                "labels.csv",
                "scopes.csv",
                "known_state.csv",
                "prices.csv",
                "statistics.json",
                "study_complete.json",
            )
        }
        write(exp.resolve(ROOT) / "protocols/result_references.json", result_refs)
        print(
            {
                "experiment": exp.experiment_id,
                "statistics": "COMPLETE",
                "new_accounts": 0,
                "provider_calls": 0,
            },
            flush=True,
        )
    except Exception as exc:
        write(
            OUT / "study_failure.json",
            {
                "status": "TECHNICAL_FAILURE",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "new_accounts": 0,
            },
        )
        raise


if __name__ == "__main__":
    {"declare": declare, "study": study}[sys.argv[1]]()
