"""Public SRT -> TXE synthetic equivalence, without real return observations."""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pandas as pd
from dataflows import Dataflows, DataSpace, Dataset, ProviderBinding, ProviderConfig, PreparePolicy
from strategy_runtime import (
    StrategyImplementation, StrategyDefinition, ParameterSet, InputContract,
    InputRequirement, CutoffRule, DecisionContract, ExecutionPolicy, MonitoringPolicy,
    RequiredCapabilities, ObservationDefinition, TradableWindow, StrategyCandidate,
    StrategyRuntime, StrategyInit, implementation_sha256,
    next_session_calendar_window, next_session_calculation_scope,
)
from trading_execution_engine import HistoricalExecutor


class SyntheticCycle(StrategyImplementation):
    """Dense independent signal fixture; only transaction semantics are tested."""
    def __init__(self, parameters):
        p = parameters.values
        self.hold = int(p["hold_days"])
        if self.hold not in (1, 2) or not -.02 <= p["entry_premium"] <= .05:
            raise ValueError("unsupported synthetic fixture")
        allocation = float(p["allocation"])
        self._definition = StrategyDefinition(
            parameters, InputContract((
                InputRequirement("market", Dataset.ETF_OHLCV.value, "518850.SH", "daily", 1, CutoffRule.SIGNAL_SESSION),
                InputRequirement("execution", Dataset.ETF_UNADJUSTED_DAILY.value, "518850.SH", "daily", 1, CutoffRule.SIGNAL_SESSION),
                InputRequirement("calendar", Dataset.TRADING_CALENDAR.value, "SSE", "daily", 0, CutoffRule.LATEST_AVAILABLE),
            )), DecisionContract("TARGET_POSITION", 0., 1., "NEXT_SESSION"),
            ExecutionPolicy("FROZEN_RULE", {
                "capital": {"fee_rate": .001, "mode": "full_available_cash" if allocation == 1 else "available_cash_fraction",
                            "allocation_fraction": allocation, "target_scope": "entry_cycle"},
                "entry": {"order_type": "LIMIT", "limit_parameter": p["entry_premium"]},
                "exit": {"order_type": "MARKET", "limit_ratio": .1},
                "instrument": {"lot_size": 100, "price_tick": .001, "price_limit_ratio": .1,
                               "maximum_order_quantity": 1000000},
            }), MonitoringPolicy("OBSERVE", {}),
            RequiredCapabilities((Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                                  Dataset.TRADING_CALENDAR.value), ("LIMIT", "MARKET")),
            "518850.SH", ObservationDefinition((), ()),
        )

    @classmethod
    def from_parameters(cls, parameters):
        return cls(parameters)

    @property
    def definition(self):
        return self._definition

    def calendar_window(self, window):
        return next_session_calendar_window(self.definition, window)

    def derive_calculation_scope(self, window, dates):
        return next_session_calculation_scope(self.definition, window, dates)

    def calculate_history(self, inputs, sessions):
        target = [float(index % (self.hold + 1) < self.hold) for index in range(len(sessions))]
        return pd.DataFrame({"target_position": target, "synthetic_target": target}, index=sessions)

    def calculate_window_history(self, inputs, sessions):
        return self.calculate_history(inputs, sessions)


def daily_prices(start, end):
    dates = pd.bdate_range(start, end)
    rows = []
    for day in dates:
        ordinal = day.date().toordinal()
        close = 10. + (ordinal % 7 - 3) * .01
        opening = 10. + (ordinal % 5 - 2) * .02
        rows.append({"Date": day, "Open": opening, "Close": close,
                     "High": max(opening, close) + .2, "Low": min(opening, close) - .2,
                     "Volume": 100., "Amount": 100. * (opening + close) / 2.})
    return pd.DataFrame(rows)


def provider(request):
    if request.dataset == Dataset.TRADING_CALENDAR:
        dates = pd.date_range(request.start, request.end)
        return pd.DataFrame({"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}), {
            "vendor": "SYNTHETIC", "primary_key": ["Date"], "exchange": "SSE"}
    frame = daily_prices(request.start, request.end)
    # Explicit synthetic evidence is derived from actual fixture values. Do not
    # call internal quality constructors or bypass the public prepare validator.
    natural = pd.date_range(request.start, request.end)
    calendar = pd.DataFrame({"Date": natural.strftime("%Y-%m-%d"),
                             "is_open": (natural.weekday < 5).astype(int)})
    def evidence_hash(value):
        digest = sha256()
        digest.update(repr([(str(c), str(t)) for c, t in value.dtypes.items()]).encode())
        digest.update(pd.util.hash_pandas_object(value, index=True).values.tobytes())
        return digest.hexdigest()
    value_columns = ("Open", "High", "Low", "Close", "Volume", "Amount")
    sessions, observations = {}, {}
    for row in frame.itertuples(index=False):
        values = {name: float(getattr(row, name)) for name in value_columns}
        day = row.Date.date().isoformat()
        sessions[day] = {"daily_complete": True, "daily_accurate": True,
                         "daily_fields": [], "daily_values": values,
                         "daily_vwap": values["Amount"] / values["Volume"],
                         "daily_low": values["Low"], "daily_high": values["High"]}
        observations[row.Date.isoformat()] = sha256(json.dumps(list(values.values()), allow_nan=False).encode()).hexdigest()
    quality = {"version": 1, "frequency": "daily", "reference_daily_sha256": evidence_hash(frame),
               "price_tolerance": .005, "volume_relative_tolerance": 1e-5,
               "amount_relative_tolerance": 1e-5, "sessions": sessions, "market": "a_share",
               "publication_adjustment": "none", "observation_sha256": observations}
    coverage = {"exchange": "SSE", "start_date": request.start, "end_date": request.end,
                "listing_date": request.start, "expected_dates": list(sessions),
                "source": "synthetic-weekday-fixture", "listing_source": "synthetic-fixture",
                "calendar_sha256": evidence_hash(calendar), "calendar": calendar.to_dict("records"),
                "verified_sessions": len(sessions)}
    return frame, {"vendor": "SYNTHETIC", "primary_key": ["Date"], "exchange": "SSE",
                   "market": "a_share", "adjustment": "none", "synthetic": True,
                   "ohlcv_quality_evidence": quality, "daily_session_coverage": coverage}


def load_accelerator():
    path = Path(__file__).with_name("accelerator.py")
    spec = importlib.util.spec_from_file_location("synthetic_transaction_accelerator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(root):
    """Creates only synthetic managed resources under the explicit .tmp area."""
    accelerator = load_accelerator()
    task_root = Path(__file__).resolve().parent
    # Public SRT authoring requires the declared strategies namespace. This
    # generated synthetic-only source copy is a test resource, not platform code.
    source_root = task_root / "synthetic-authoring/strategy_runtime"
    fixture = source_root / "strategies/synthetic_fixture.py"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes(Path(__file__).read_bytes())
    sources = ("strategies/synthetic_fixture.py",)
    digest = implementation_sha256(sources, source_root=source_root)
    flows = Dataflows(base_dir=root, space=DataSpace(Path(".tmp/s012-stage3-20261005/synthetic-data")),
                     providers=ProviderConfig(bindings={dataset: ProviderBinding("synthetic", "s012-v1", provider)
                         for dataset in (Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY, Dataset.TRADING_CALENDAR)}))
    window = TradableWindow(pd.Timestamp("2020-06-08").date(), pd.Timestamp("2020-06-26").date())
    daily = daily_prices("2020-06-05", "2020-06-26")
    intraday = daily.rename(columns={"Date": "dt", "Open": "open", "High": "high", "Low": "low", "Close": "close"})
    intraday["dt"] = intraday.dt + pd.Timedelta(hours=10)
    full_daily = daily.rename(columns={"Date": "dt", "Open": "open", "High": "high", "Low": "low", "Close": "close"})
    rows = []
    for index, (hold, allocation, premium) in enumerate(
        [(1, 1., 0.), (2, 1., 0.), (1, .5, 0.), (2, .5, 0.),
         (1, 1., .01), (2, .5, .01), (1, 1., -.005), (2, .5, -.005)], start=1):
        parameters = {"hold_days": hold, "allocation": allocation, "entry_premium": premium}
        candidate = StrategyCandidate("S012", f"C{9000+index:04d}", {
            "runtime": {"module": "strategy_runtime.strategies.synthetic_fixture", "qualname": "SyntheticCycle", "contract_version": 1,
                        "source_files": sources, "source_sha256": digest}, "parameters": parameters}, source_root)
        instance = StrategyRuntime(dataflows=flows).create(StrategyInit(candidate, window,
                   source_root / "synthetic-contexts" / candidate.candidate_id))
        instance.prepare_data(policy=PreparePolicy.REUSE)
        executor = HistoricalExecutor(strategy_reference=candidate.reference_id, symbol="518850.SH",
                     execution_daily=full_daily, execution_intraday=intraday,
                     evaluation_start=pd.Timestamp(window.start), evaluation_end=pd.Timestamp(window.end),
                     initial_cash=100000., execution_policy=instance.definition.execution,
                     order_types=("LIMIT", "MARKET"))
        full = instance.run_window(executor=executor)
        fast = accelerator.simulate(SyntheticCycle(ParameterSet(parameters)), pd.DataFrame(), daily, intraday,
                                   start=window.start.isoformat(), end=window.end.isoformat())
        comparison = accelerator.compare_economics(fast, {name: getattr(full, name)
                                                   for name in ("account_daily", "orders", "fills", "trades")})
        full_targets = instance.inspect_signals().target_position
        fast_targets = fast["signals"].target_position.copy()
        full_targets.index = full_targets.index.astype("datetime64[ns]")
        fast_targets.index = fast_targets.index.astype("datetime64[ns]")
        pd.testing.assert_series_equal(fast_targets, full_targets)
        rows.append({"parameters": parameters, "comparison": comparison,
                     "signal_rows": len(full_targets), "data_binding_identity": instance.input_binding.identity,
                     "full_ledgers": {name: json.loads(getattr(full, name).to_json(
                             orient="table", date_format="iso", double_precision=15, index=False))
                             for name in ("account_daily", "orders", "fills", "trades")},
                     "accelerated_ledgers": {name: json.loads(fast[name].to_json(
                             orient="table", date_format="iso", double_precision=15, index=False))
                             for name in ("account_daily", "orders", "fills", "trades")},
                     "synthetic_account_file_identity": sha256(full.account_daily.to_json(date_format="iso").encode()).hexdigest()})
    return {"status": "PASS", "scope": "synthetic transaction equivalence only; no real performance",
            "source_sha256": digest,
            "accelerator_sha256": sha256(Path(__file__).with_name("accelerator.py").read_bytes()).hexdigest(),
            "comparison_atol": 1e-8, "comparison_rtol": 1e-12,
            "cases": rows, "real_11_case_approval": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".tmp/s012-stage3-20261005/synthetic_equivalence.json")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    result = run(root)
    target = (root / args.output).resolve()
    target.relative_to(root / ".tmp")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "cases": len(result["cases"])}))


if __name__ == "__main__":
    main()
