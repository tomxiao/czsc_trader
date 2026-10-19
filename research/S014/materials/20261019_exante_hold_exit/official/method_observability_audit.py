"""Independent observable formulas/state clock audit, never an account dispatch."""

import ast
from collections import Counter, defaultdict
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import socket
import statistics
import sys
from uuid import UUID

import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef
from czsc_trader.research_tools import EvidenceRef

sys.dont_write_bytecode = True
ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
SOURCE = (
    ROOT
    / "research/S014/experiments/EX043_20261019/src/strategy_runtime/strategies/exante_hold_exit.py"
)
OLD = ROOT / "research/S014/experiments/EX023_20261018/src/strategy_runtime/strategies/repair.py"
sys.path.append(str(ROOT / "research/S014/experiments/EX017_20261017/src"))
from pinned_inputs import get_context  # noqa: E402

ATTEMPTS = []
COUNTS = Counter()
ERRORS = defaultdict(float)


def prohibit(*args, **kwargs):
    ATTEMPTS.append("network")
    raise RuntimeError("Only authenticated PreparedDataRef offline fetch permitted")


requests.sessions.Session.request = prohibit
socket.socket.connect = prohibit
socket.create_connection = prohibit


def check(name, value):
    if not bool(value):
        raise AssertionError(name)
    COUNTS[name] += 1


def number(name, actual, expected):
    if not math.isfinite(expected):
        check(name + " unknown mask", pd.isna(actual))
        return
    error = abs(float(actual) - expected)
    ERRORS[name] = max(ERRORS[name], error)
    check(
        name,
        math.isfinite(float(actual))
        and math.isclose(float(actual), expected, rel_tol=1e-10, abs_tol=1e-10),
    )


def published(raw):
    ref = EvidenceRef.from_dict(raw)
    check("only S014 evidence", ref.experiment.strategy_id == "S014")
    content = ref.resolve(ROOT).read_bytes()
    check("public evidence byte hash", sha256(content).hexdigest() == ref.sha256)
    return json.loads(content)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def oracle(frame):
    """Direct finite slices/math, independent of rolling implementation."""
    rows = list(frame.itertuples(index=False))
    dates = pd.to_datetime(frame.Date)
    closes = [float(x.Close) for x in rows]
    true_ranges, returns = [], []
    for i, x in enumerate(rows):
        valid = dates.iloc[i] >= pd.Timestamp("2020-01-02") and i > 0
        true_ranges.append(
            max(
                float(x.High - x.Low),
                abs(float(x.High) - closes[i - 1]),
                abs(float(x.Low) - closes[i - 1]),
            )
            if valid
            else math.nan
        )
        returns.append(math.log(closes[i] / closes[i - 1]) if valid else math.nan)
    masked_closes = [
        c if d >= pd.Timestamp("2020-01-02") else math.nan for c, d in zip(closes, dates)
    ]

    def mean(values, start, end, count):
        part = values[max(0, start) : end]
        return (
            math.fsum(part) / count
            if start >= 0 and len(part) == count and all(math.isfinite(v) for v in part)
            else math.nan
        )

    result = []
    for i in range(len(rows)):
        ma = mean(masked_closes, i - 20, i, 20)
        lag = mean(masked_closes, i - 25, i - 5, 20)
        atr = mean(true_ranges, i - 20, i, 20)
        r5 = mean(returns, i - 4, i + 1, 5)
        r5 = r5 * 5 if math.isfinite(r5) else math.nan
        sample = returns[max(0, i - 24) : i - 4]
        sigma = (
            statistics.stdev(sample)
            if i >= 24 and len(sample) == 20 and all(math.isfinite(v) for v in sample)
            else math.nan
        )
        z = (
            r5 / (math.sqrt(5) * sigma)
            if math.isfinite(r5) and math.isfinite(sigma) and sigma > 0
            else math.nan
        )
        result.append(
            dict(
                ma20_prior=ma,
                ma20_prior_lag5=lag,
                atr20_prior=atr,
                ret5_log=r5,
                sigma20_pre5=sigma,
                z5=z,
            )
        )
    return result


def main():
    destination = HERE / "method_observability_audit.json"
    if destination.exists():
        raise FileExistsError("Preserve audit; use a reviewed successor if source changes")
    source_hash = sha256(SOURCE.read_bytes()).hexdigest()
    code, old = load(SOURCE, "observable_source"), load(OLD, "observable_original")
    record = json.loads(
        (
            ROOT / "research/S014/experiments/EX040_20261019/others/accounts/run-003.json"
        ).read_bytes()
    )
    binding = published(record["binding_ref"])
    rawref = binding["execution_prepared"]
    prepared = PreparedDataRef(
        UUID(rawref["space_id"]), UUID(rawref["preparation_id"]), rawref["manifest_sha256"]
    )
    context = get_context()
    frames, identities = {}, {}
    for name, key in [
        ("market", "adjusted_daily"),
        ("raw", "execution_daily"),
        ("limits", "price_limits"),
        ("status", "trading_status"),
    ]:
        request_dict = binding["execution_requests"][key]
        request = DataRequest(
            Dataset(request_dict["dataset"]),
            request_dict["symbol"],
            request_dict["start"],
            request_dict["end"],
            request_dict["required_cutoff"],
            request_dict["frequency"],
        )
        fetched = context.data.fetch(request, prepared=prepared)
        check(
            "same authenticated prepared content",
            fetched.ready
            and fetched.identity.content_sha256 == binding["execution_identities"][key],
        )
        frames[name] = fetched.dataframe.copy(deep=True)
        identities[name] = dict(
            request=request_dict,
            content_sha256=fetched.identity.content_sha256,
            rows=len(frames[name]),
        )
    market = frames["market"].sort_values("Date").reset_index(drop=True)
    frames["market"] = market
    source_features = code.causal_features(market)
    independent = oracle(market)
    for i, expected in enumerate(independent):
        actual = source_features.iloc[i]
        for key, value in expected.items():
            number("feature " + key, actual[key], value)
        for key, value in dict(
            ma_known=math.isfinite(expected["ma20_prior"])
            and math.isfinite(expected["ma20_prior_lag5"]),
            atr_known=math.isfinite(expected["atr20_prior"]),
            atr_positive=math.isfinite(expected["atr20_prior"]) and expected["atr20_prior"] > 0,
            sigma20_known=math.isfinite(expected["sigma20_pre5"]),
            sigma20_positive=math.isfinite(expected["sigma20_pre5"])
            and expected["sigma20_pre5"] > 0,
            shock_known=math.isfinite(expected["z5"]),
        ).items():
            check("independent feature known " + key, bool(actual[key]) == value)
    # Every feature value at D recomputed using only its own completed prefix.
    for i in range(len(market)):
        observed = code.causal_features(market.iloc[: i + 1]).iloc[-1]
        for key, value in independent[i].items():
            number("prefix feature " + key, observed[key], value)
    check(
        "no rule parameters encode dates/years",
        set(
            code.HoldExitConfig.parse(
                {"hold_rule": "BASE", "exit_rule": "BASE"}
            ).__dataclass_fields__
        )
        == {"hold_rule", "exit_rule"},
    )
    # Direct AST/identity comparisons focus economic policy and original requests.
    tree, oldtree = (
        ast.parse(SOURCE.read_text(encoding="utf-8")),
        ast.parse(OLD.read_text(encoding="utf-8")),
    )
    for name in [
        "InputContract",
        "DecisionContract",
        "ExecutionPolicy",
        "MonitoringPolicy",
        "RequiredCapabilities",
    ]:

        def call(t):
            return next(
                x
                for x in ast.walk(t)
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == name
            )

        check("original economic AST " + name, ast.dump(call(tree)) == ast.dump(call(oldtree)))
    output = {}
    trigger_records = []
    for hold in code.HoldRule:
        for exit_rule in code.ExitRule:
            cfg = code.HoldExitConfig(hold, exit_rule)
            label = hold.value + "__" + exit_rule.value
            history = code.history(
                frames["market"], frames["raw"], frames["limits"], frames["status"], cfg
            )
            if label == "BASE__BASE":
                baseline = old.history(
                    frames["market"],
                    frames["raw"],
                    frames["limits"],
                    frames["status"],
                    "support_exit_reserve_H10",
                )
                pd.testing.assert_frame_equal(history[baseline.columns], baseline, check_exact=True)
                check("source-history BASE BASE original exact", True)
            years = {str(y): Counter() for y in range(2020, 2026)}
            protected = False
            prior_pending = False
            prior_giveback = False
            for i, (stamp, row) in enumerate(history.iterrows()):
                feat = independent[i]
                held, bought, sold = (
                    bool(row.held_at_close),
                    bool(row.buy_filled_today),
                    bool(row.sell_filled_today),
                )
                inherited = prior_pending and held and not sold
                expired = held and i >= row.deadline_index
                eligible = held and not inherited and not expired
                check("pending inherited exact", bool(row.pending_inherited) == inherited)
                check("mandatory deadline exact", bool(row.deadline_exit) == expired)
                check("discretionary eligibility exact", bool(row.profit_exit_eligible) == eligible)
                if bought or sold:
                    protected = False
                shock = giveback = grace = trend = selected = suppressed = False
                if held:
                    entry = int(row.entry_index)
                    c = float(market.Close.iloc[i])
                    peak = max(float(x) for x in market.Close.iloc[entry : i + 1])
                    net = c * 0.999 / (row.entry_fill_price * 1.001) - 1
                    gain = peak * 0.999 - row.entry_fill_price * 1.001
                    back = peak - c
                    for key, value in [
                        ("peak_close", peak),
                        ("net_profit", net),
                        ("peak_net_gain_price", gain),
                        ("giveback_price", back),
                    ]:
                        number("holding " + key, row[key], value)
                    check(
                        "actual cycle age and known peak",
                        row.holding_age == i - entry and row.peak_known == 1,
                    )
                    if bought:
                        check(
                            "entry close-only peak zero giveback", back == 0 and row.peak_close == c
                        )
                    shock = eligible and math.isfinite(feat["z5"]) and net > 0 and feat["z5"] > 2
                    giveback = (
                        eligible
                        and math.isfinite(feat["atr20_prior"])
                        and feat["atr20_prior"] > 0
                        and gain >= 2 * feat["atr20_prior"]
                        and back >= feat["atr20_prior"]
                    )
                    grace = eligible and bought and bool(row.support_break)
                    trend = (
                        grace
                        and math.isfinite(feat["ma20_prior"])
                        and math.isfinite(feat["ma20_prior_lag5"])
                        and math.isfinite(feat["atr20_prior"])
                        and feat["atr20_prior"] > 0
                        and c >= feat["ma20_prior"]
                        and feat["ma20_prior"] > feat["ma20_prior_lag5"]
                        and (row.support_floor - c) / feat["atr20_prior"] <= 1
                    )
                    activated = hold.value == "TREND_CYCLE" and trend
                    if activated:
                        protected = True
                    guard = (hold.value == "ENTRY_GRACE" and grace) or (
                        hold.value == "TREND_CYCLE" and protected
                    )
                    selected = (exit_rule.value == "SHOCK_PROFIT" and shock) or (
                        exit_rule.value == "PROFIT_GIVEBACK" and giveback
                    )
                    ordinary = eligible and bool(row.support_break) and not guard
                    suppressed = eligible and bool(row.support_break) and guard and not selected
                    for key, value in dict(
                        shock_condition=shock,
                        giveback_condition=giveback,
                        entry_grace_eligible=grace,
                        trend_cycle_eligible=trend,
                        trend_cycle_activated=activated,
                        trend_cycle_active=protected,
                        selected_profit_exit=selected,
                        support_exit_suppressed=suppressed,
                        ordinary_support_exit=ordinary,
                        profit_exit_added_vs_base_support=selected and not row.support_break,
                        profit_exit_added_vs_selected_hold=selected and not ordinary,
                    ).items():
                        check("independent state " + key, bool(row[key]) == bool(value))
                    check(
                        "exact pending priority",
                        bool(row.exit_pending)
                        == bool(inherited or expired or selected or ordinary),
                    )
                    check("exact held target", row.target_position == float(not row.exit_pending))
                    if 2020 <= stamp.year <= 2025 and (
                        shock or giveback or activated or suppressed
                    ):
                        rec = dict(
                            path=label,
                            D=stamp.date().isoformat(),
                            entry_D=history.index[entry].date().isoformat(),
                            holding_age=i - entry,
                            shock=bool(shock),
                            giveback=bool(giveback),
                            selected=bool(selected),
                            trend_activated=bool(activated),
                            support_suppressed=bool(suppressed),
                            ret5_log=feat["ret5_log"],
                            raw_five_session_return=math.expm1(feat["ret5_log"])
                            if math.isfinite(feat["ret5_log"])
                            else None,
                            sigma20_pre5=feat["sigma20_pre5"],
                            z5=feat["z5"],
                            net_profit=net,
                            peak_gain_in_current_ATR=gain / feat["atr20_prior"]
                            if feat["atr20_prior"] > 0
                            else None,
                            giveback_in_current_ATR=back / feat["atr20_prior"]
                            if feat["atr20_prior"] > 0
                            else None,
                        )
                        # Descriptive scale-shrink transition: no new downside close, same cycle.
                        transition = False
                        old_scale_pass = None
                        if (
                            i > 0
                            and giveback
                            and not prior_giveback
                            and row.entry_index == history.iloc[i - 1].entry_index
                        ):
                            previous_atr = independent[i - 1]["atr20_prior"]
                            old_scale_pass = bool(
                                previous_atr > 0
                                and gain >= 2 * previous_atr
                                and back >= previous_atr
                            )
                            transition = bool(
                                c >= float(market.Close.iloc[i - 1])
                                and feat["atr20_prior"] < previous_atr
                                and not old_scale_pass
                            )
                        rec.update(
                            giveback_false_to_true_without_new_down_close_due_scale_shrink=transition,
                            passes_current_price_conditions_under_previous_ATR=old_scale_pass,
                        )
                        trigger_records.append(rec)
                else:
                    check(
                        "flat peak/entry state cleared",
                        pd.isna(row.peak_close)
                        and pd.isna(row.entry_fill_price)
                        and row.peak_known == 0
                        and row.holding_age == -1,
                    )
                if 2020 <= stamp.year <= 2025:
                    counts = years[str(stamp.year)]
                    counts["D_rows"] += 1
                    for key, value in dict(
                        held=held,
                        bought=bought,
                        discretionary=eligible,
                        shock=shock,
                        giveback=giveback,
                        grace_eligible=grace,
                        trend_eligible=trend,
                        selected_exit=selected,
                        support_suppressed=suppressed,
                        ma_unknown=not bool(row.ma_known),
                        atr_unknown=not bool(row.atr_known),
                        shock_unknown=not bool(row.shock_known),
                    ).items():
                        counts[key] += int(value)
                prior_pending = bool(row.exit_pending)
                prior_giveback = bool(giveback)
            # History-prefix tests do not invoke the account system.
            for cutoff in ["2020-12-31", "2025-12-31"]:
                prefix = {
                    key: frame.loc[pd.to_datetime(frame.Date) <= pd.Timestamp(cutoff)].copy()
                    for key, frame in frames.items()
                }
                recomputed = code.history(
                    prefix["market"], prefix["raw"], prefix["limits"], prefix["status"], cfg
                )
                pd.testing.assert_frame_equal(
                    recomputed, history.loc[recomputed.index], check_exact=True
                )
                check("history causal prefix " + label, True)
            output[label] = {
                "annual_activation": {y: dict(c) for y, c in years.items()},
                "economic_or_account_run": False,
            }
    check("zero network attempts", not ATTEMPTS)
    check("source unchanged during audit", sha256(SOURCE.read_bytes()).hexdigest() == source_hash)
    result = dict(
        status="PASS_INDEPENDENT_OBSERVABILITY_FORMULAS_CLOCK_AND_SOURCE_STATE",
        source_sha256=source_hash,
        source_path=SOURCE.relative_to(ROOT).as_posix(),
        audit_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        prepared=rawref,
        input_identity=identities,
        checks=sum(COUNTS.values()),
        check_counts=dict(COUNTS),
        maximum_formula_errors=dict(ERRORS),
        paths=output,
        trigger_rows=trigger_records,
        descriptive_competing_explanations={
            "giveback_scale_shrink_no_new_down_close_count": sum(
                x["giveback_false_to_true_without_new_down_close_due_scale_shrink"]
                for x in trigger_records
            ),
            "shock_scale_note": "All shock records retain raw five-session return, prior20 sigma and Z. Smaller raw returns with Z>2 describe denominator amplification; no retrospective small-return cutoff or new trade filter is introduced.",
            "not_independent_events": "rows repeat across overlapping policies and cycles; retain path/entry_D, not independent sample counts",
        },
        scope="Read-only source history state and original authenticated prepared prices; no true accounts, cash returns, labels, fits, data prepare, supplier calls or raw market exports. 2020-25 activations, original2026 input tail only for prefix/control.",
        new_account_dispatches=0,
        new_market_provider_calls=0,
        new_data_preparations=0,
        new_fits=0,
        new_return_labels=0,
        network_attempts=ATTEMPTS,
    )
    # Derived diagnostic rows only; raw OHLCV frames remain in memory.
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in [
                    "status",
                    "source_sha256",
                    "checks",
                    "descriptive_competing_explanations",
                ]
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
