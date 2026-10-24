"""Compare public SRT plans at two clocks on retained account pre-states.

No executor, account simulation, strategy evaluation or provider preparation.
"""

# ruff: noqa: E402
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, time
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import Dataflows, DataSpace, ProviderConfig
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import (
    EntryCycleState,
    ExecutionState,
    ExecutionPricing,
    PortfolioSnapshot,
    SignalHistoryMode,
    StrategyCandidate,
    StrategyInit,
    StrategyInputBinding,
    StrategyRuntime,
    TradingPoint,
)

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
BASE = ROOT / "research/S015/experiments"
ZONE = ZoneInfo("Asia/Shanghai")


def read(path):
    return json.loads(path.read_bytes())


def encode(value):
    if is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def check(experiment, cid):
    home = BASE / experiment
    row = next(x for x in read(home / "others/results.json")["rows"] if x["candidate_id"] == cid)
    reference = EvidenceRef.from_dict(row["evidence"])
    evidence = read(reference.resolve(ROOT))
    run = next(x for x in evidence["runs"] if x["window_id"] == "full")
    payload = read(home / f"others/{cid}_payload.json")
    source = home / "src/strategy_runtime"
    source_refs = []
    published = read(home / "others/protocol_refs.json")
    for filename in payload["runtime"]["source_files"]:
        path = source / filename
        ref = EvidenceRef.from_dict(published[str(path.relative_to(ROOT))])
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        source_refs.append(ref.to_dict())
    candidate = StrategyCandidate("S015", cid, payload, source)
    binding = StrategyInputBinding.from_mapping(evidence["input_bindings"]["full"])
    pricing = ExecutionPricing.from_dict(evidence["request_identity"]["pricing"])
    flows = Dataflows(
        base_dir=ROOT,
        space=DataSpace(Path("research/S015/assets/data")),
        providers=ProviderConfig(bindings={}),
    )
    instance = StrategyRuntime(dataflows=flows).create(
        StrategyInit(
            candidate,
            binding.plan.tradable_window,
            ROOT / f".tmp/s015-clock-check-{cid}",
            pricing=pricing,
        )
    )
    preparation = instance.prepare_data(binding=binding)
    assert preparation.available_through.isoformat() == run["signal_support"]["available_through"]
    intraday = flows.fetch(binding.plan.requests["intraday"], prepared=binding.prepared)
    assert intraday.ready, intraday.error
    dt = pd.to_datetime(intraday.dataframe.Date)
    assert dt.dt.strftime("%H:%M").max() == "15:00"
    assert (dt.groupby(dt.dt.normalize()).size() == 8).all()
    daily = pd.DataFrame(run["ledgers"]["account_daily"]["data"])
    decisions = pd.DataFrame(run["ledgers"]["decisions"]["data"])
    execution = pd.DataFrame(run["replay_evidence"]["execution_daily"])
    execution.index = pd.to_datetime(execution.date).dt.date
    assert len(daily) == len(decisions) == len(binding.plan.signal_dates) == 434
    pairs = []
    for index, (trading_day, signal_day) in enumerate(binding.plan.signal_dates.items()):
        actual = daily.iloc[index]
        decision = decisions.iloc[index]
        assert str(actual.date)[:10] == trading_day.isoformat()
        assert str(decision.signal_date)[:10] == signal_day.isoformat()
        cash, quantity = float(actual.cash_before), int(actual.quantity_before)
        state_raw = json.loads(decision.entry_cycle_before)
        cycle = None if state_raw is None else EntryCycleState.from_dict(state_raw)
        # Both plans receive the identical authoritative monetary/holding/cycle
        # pre-state. Revision is a sequential audit token, not a new execution.
        as_of = datetime.combine(signal_day, time(15), tzinfo=ZONE)
        close = float(execution.loc[signal_day, "close"])
        portfolio = PortfolioSnapshot(
            "backtest-account",
            "159326.SZ",
            Decimal(str(cash)),
            Decimal(str(cash + quantity * close)),
            quantity,
            index,
            as_of,
            pricing=pricing,
        )
        state = ExecutionState(
            index, as_of, None if cycle is None else cycle.target_quantity, entry_cycle=cycle
        )
        plans = [
            instance.plan_at(
                point=TradingPoint(trading_day, datetime.combine(signal_day, clock, tzinfo=ZONE)),
                portfolio=portfolio,
                state=state,
                history_mode=SignalHistoryMode.WINDOW,
            )
            for clock in (time(17, 30), time(20, 31))
        ]
        encoded = [encode(plan) for plan in plans]
        timestamps = [value.pop("generated_at") for value in encoded]
        assert encoded[0] == encoded[1], (cid, trading_day, "clock-specific plan differs")
        assert plans[0].plan_identity == plans[1].plan_identity == decision.plan_identity, (
            cid,
            trading_day,
            "retained plan identity differs",
        )
        assert plans[0].signal_identity == decision.signal_identity
        pairs.append(
            {
                "trading_day": trading_day.isoformat(),
                "signal_day": signal_day.isoformat(),
                "generated_at": timestamps,
                "plan_identity": plans[0].plan_identity,
                "economic_plan_sha256": sha256(
                    json.dumps(encoded[0], sort_keys=True, allow_nan=False).encode()
                ).hexdigest(),
            }
        )
    return {
        "candidate": cid,
        "experiment": experiment,
        "window": "full",
        "sessions": len(pairs),
        "evidence": reference.to_dict(),
        "implementation_evidence": source_refs,
        "input_binding_identity": binding.identity,
        "retained_available_through": preparation.available_through.isoformat(),
        "intraday_rows": len(dt),
        "intraday_session_times": sorted(dt.dt.strftime("%H:%M").unique().tolist()),
        "all_plans_equal_except_generated_at": True,
        "all_plan_and_signal_identities_equal_retained_account": True,
        "pairs": pairs,
    }


def main():
    output = HERE / "others/clock_checks.json"
    assert not output.exists()
    result = {
        "status": "PENDING",
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "new_account_simulations": 0,
        "new_formal_evaluations": 0,
        "checks": [],
        "limitations": [
            "Formal historical accounts retain the runtime default T20:31 convention; they are not rewritten as 17:30 accounts.",
            "Equivalence is conditional on authenticated bound inputs and retained actual cash, quantity and entry-cycle pre-states.",
            "No HistoricalExecutor was constructed, no fills were simulated, and no account count is added.",
            "This does not establish historical provider publication/revision availability at 17:30.",
            "The two representative full434 paths do not cover all candidate variants or other windows.",
        ],
    }
    try:
        for experiment, cid in (("EX061_20261024", "C6105"), ("EX061_20261024", "C6117")):
            result["checks"].append(check(experiment, cid))
            print("CLOCK_CHECKED", cid, flush=True)
        result["status"] = "PASS"
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "candidates": len(result["checks"]),
                    "new_account_simulations": 0,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
