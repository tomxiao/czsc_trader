"""Independent bounded clock-transition audit; no funded account or return calculation."""

import ast
from collections import Counter
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys
from uuid import UUID

import numpy as np
import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef
from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
SOURCE = (
    ROOT
    / "research/S014/experiments/EX045_20261019/src/strategy_runtime/strategies/blocked_clock_review.py"
)
OLD = (
    ROOT
    / "research/S014/experiments/EX044_20261019/src/strategy_runtime/strategies/action_role_review.py"
)
COUNTS = Counter()
ATTEMPTS = []


def check(name, condition):
    if not bool(condition):
        raise AssertionError(name)
    COUNTS[name] += 1


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prohibit(*args, **kwargs):
    ATTEMPTS.append("network")
    raise RuntimeError("Existing offline prepared inputs only")


def synthetic(code):
    dates = pd.bdate_range("2020-01-02", periods=95)
    market = pd.DataFrame(
        {"Date": dates, "Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0}
    )
    bounds = pd.DataFrame({"Date": dates, "DownLimit": 80.0, "UpLimit": 120.0})
    states = pd.DataFrame({"Date": dates, "Status": "TRADING"})
    features = code.causal_features(market)
    features["shock_known"] = True
    features["z5"] = 0.0
    features.iloc[59, features.columns.get_loc("z5")] = 3.0
    features.iloc[70, features.columns.get_loc("z5")] = 3.0
    original = code.causal_features

    def run(profile, f=features, m=market):
        code.causal_features = lambda prices: f.loc[pd.to_datetime(prices.Date)].copy()
        try:
            return code.history(
                m, m.copy(), bounds, states, code.ClockConfig.parse({"clock_profile": profile})
            )
        finally:
            code.causal_features = original

    keep = run("KEEP_PLANNED_SLOT")
    retry = run("RETRY_EACH_D")
    check(
        "slot consume i59 reserves70 no phantom fill",
        keep.iloc[59].gate_slot_consumed == 1
        and keep.iloc[59].reservation_index == 70
        and keep.iloc[59].held_at_close == 0
        and keep.iloc[59].entry_index == -1
        and keep.iloc[59].deadline_index == -1
        and pd.isna(keep.iloc[59].cost_loss_price)
        and keep.iloc[59].target_position == 0
        and keep.iloc[59].failed_buy_reset == 0,
    )
    check(
        "no candidate or consume inside original slot",
        keep.iloc[60:70].original_entry_candidate.eq(0).all()
        and keep.iloc[60:70].gate_slot_consumed.eq(0).all()
        and keep.iloc[59:70].planned_slot_active.eq(1).all(),
    )
    check(
        "expiry D70 can reblock reserves81",
        keep.iloc[70].gate_slot_consumed == 1
        and keep.iloc[70].reservation_before_gate == 70
        and keep.iloc[70].reservation_index == 81,
    )
    check(
        "expiry D81 sends next E82 buy only",
        keep.iloc[81].entry_signal == 1
        and keep.iloc[81].buy_filled_today == 0
        and keep.iloc[82].buy_filled_today == 1
        and keep.iloc[82].entry_index == 82
        and keep.iloc[82].deadline_index == 91
        and keep.iloc[82].reservation_index == 92
        and keep.iloc[82].planned_slot_until == -1,
    )
    check(
        "retry original next D candidate",
        retry.iloc[59].reservation_index == -1
        and retry.iloc[60].entry_signal == 1
        and retry.iloc[61].buy_filled_today == 1,
    )
    equal = features.copy()
    equal.iloc[59, equal.columns.get_loc("z5")] = 2.0
    check("strict Z2 not blocked", run("KEEP_PLANNED_SLOT", equal).iloc[59].entry_signal == 1)
    equal.iloc[59, equal.columns.get_loc("z5")] = 3.0
    equal.iloc[59, equal.columns.get_loc("shock_known")] = False
    check("unknown score not blocked", run("KEEP_PLANNED_SLOT", equal).iloc[59].entry_signal == 1)
    # An original attempted BUY actually fails: do not consume a hypothetical slot.
    f = features.copy()
    f["z5"] = 0.0
    gap = market.copy()
    gap.loc[60, ["Open", "High", "Low", "Close"]] = [104.0, 104.0, 103.0, 103.0]
    failed = run("KEEP_PLANNED_SLOT", f, gap)
    check(
        "true failed BUY original reset and no slot",
        failed.iloc[60].failed_buy_reset == 1
        and failed.iloc[60].gate_slot_consumed == 0
        and failed.iloc[60].reservation_index == -1
        and failed.iloc[60].entry_signal == 0
        and failed.iloc[60].entry_index == -1,
    )


def main():
    destination = HERE / "clock_source_state_review.json"
    if destination.exists():
        raise FileExistsError(destination)
    expected = "07088482b6a183e8315f9fc23c3eaeee44dbe840aa598f86f89201d59e925b68"
    check("stable new source hash", digest(SOURCE) == expected)
    check(
        "frozen source hash",
        digest(OLD) == "e176e01873d67fff2c869915373f36b35f1f507524a5583c49b138b3c146b527",
    )
    design = HERE.parent / "clock_followup_design.json"
    check(
        "fixed followup design",
        digest(design) == "80ba902aca0662d9a604eb6d4f2d8b03f2d8a7208ee683dcedc41cf2de6a7989",
    )
    trees = [ast.parse(p.read_text(encoding="utf-8")) for p in [SOURCE, OLD]]
    for name in [
        "causal_features",
        "tick",
        "buy_limit",
        "calendar_request",
        "derive_calculation_scope",
    ]:
        functions = [
            next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name)
            for t in trees
        ]
        check(
            "unchanged feature and execution helper AST " + name,
            ast.dump(functions[0]) == ast.dump(functions[1]),
        )
    for name in [
        "InputContract",
        "DecisionContract",
        "ExecutionPolicy",
        "MonitoringPolicy",
        "RequiredCapabilities",
    ]:
        nodes = [
            next(
                n
                for n in ast.walk(t)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
            )
            for t in trees
        ]
        check("unchanged economic contract AST " + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    code, old = load(SOURCE, "independent_clock"), load(OLD, "independent_clock_prior")
    for invalid in [
        {"clock_profile": True},
        {"clock_profile": "x"},
        {"clock_profile": "KEEP_PLANNED_SLOT", "entry_guard": "BASE"},
    ]:
        try:
            code.ClockConfig.parse(invalid)
        except ValueError:
            check("invalid parameter rejected", True)
        else:
            raise AssertionError("invalid parameter accepted")
    synthetic(code)
    requests.sessions.Session.request = prohibit
    socket.socket.connect = prohibit
    socket.create_connection = prohibit
    record = json.loads(
        (
            ROOT / "research/S014/experiments/EX040_20261019/others/accounts/run-003.json"
        ).read_bytes()
    )
    ref = EvidenceRef.from_dict(record["binding_ref"])
    content = ref.resolve(ROOT).read_bytes()
    check("public binding bytes", sha256(content).hexdigest() == ref.sha256)
    binding = json.loads(content)
    prep = binding["execution_prepared"]
    prepared = PreparedDataRef(
        UUID(prep["space_id"]), UUID(prep["preparation_id"]), prep["manifest_sha256"]
    )
    sys.path.append(str(ROOT / "research/S014/experiments/EX017_20261017/src"))
    from pinned_inputs import get_context

    context = get_context()
    frames, identities = {}, {}
    for name, key in [
        ("market", "adjusted_daily"),
        ("raw", "execution_daily"),
        ("limits", "price_limits"),
        ("status", "trading_status"),
    ]:
        r = binding["execution_requests"][key]
        fetched = context.data.fetch(
            DataRequest(
                Dataset(r["dataset"]),
                r["symbol"],
                r["start"],
                r["end"],
                r["required_cutoff"],
                r["frequency"],
            ),
            prepared=prepared,
        )
        check(
            "original authenticated prepared content",
            fetched.ready
            and fetched.identity.content_sha256 == binding["execution_identities"][key],
        )
        frames[name] = fetched.dataframe.sort_values("Date").reset_index(drop=True)
        identities[name] = fetched.identity.content_sha256
    baseline = old.history(
        **frames,
        config=old.ActionRoleConfig.parse(
            {"entry_guard": "BLOCK_SHOCK", "exit_domain": "POSITIVE_P", "cost_stop": "BASE"}
        ),
    )
    for profile in ["RETRY_EACH_D", "KEEP_PLANNED_SLOT"]:
        history = code.history(**frames, config=code.ClockConfig.parse({"clock_profile": profile}))
        if profile == "RETRY_EACH_D":
            pd.testing.assert_frame_equal(history[baseline.columns], baseline, check_exact=True)
            check("fresh source RETRY all prior columns exact", True)
        for i, r in enumerate(history.itertuples()):
            consumed = bool(profile == "KEEP_PLANNED_SLOT" and r.entry_guard_blocked)
            check(
                "only blocked candidate consumes slot",
                bool(r.gate_slot_consumed) == consumed
                and (not consumed or r.original_entry_candidate == 1),
            )
            expected_reserve = (
                i + 10
                if r.buy_filled_today
                else (i + 11 if consumed else (history.iloc[i - 1].reservation_index if i else -1))
            )
            check(
                "reservation only actualfill or explicit gate slot",
                r.reservation_index == expected_reserve,
            )
            check(
                "beforegate after actualfill exact",
                r.reservation_before_gate
                == (
                    i + 10
                    if r.buy_filled_today
                    else history.iloc[i - 1].reservation_index
                    if i
                    else -1
                ),
            )
            check(
                "slot known numeric finite diagnostics",
                all(np.isfinite(getattr(r, key)) for key in code.SLOT_DIAGNOSTIC),
            )
            check(
                "slot active exact",
                bool(r.planned_slot_active)
                == bool(
                    not r.held_at_close and r.planned_slot_until >= 0 and i < r.planned_slot_until
                ),
            )
            if consumed:
                check(
                    "slot never creates actual state",
                    r.target_position == 0
                    and r.entry_signal == 0
                    and r.held_at_close == 0
                    and r.buy_filled_today == 0
                    and r.failed_buy_reset == 0
                    and r.entry_index == -1
                    and r.deadline_index == -1
                    and pd.isna(r.entry_fill_price)
                    and pd.isna(r.peak_close)
                    and pd.isna(r.cost_loss_price),
                )
            if r.buy_filled_today:
                check(
                    "real fill original anchors and clears slot",
                    r.entry_index == i
                    and r.deadline_index == i + 9
                    and r.reservation_index == i + 10
                    and r.planned_slot_until == -1,
                )
        for cutoff in ["2024-10-09", "2025-12-31"]:
            prefix = {
                k: f.loc[pd.to_datetime(f.Date) <= pd.Timestamp(cutoff)].copy()
                for k, f in frames.items()
            }
            p = code.history(**prefix, config=code.ClockConfig.parse({"clock_profile": profile}))
            pd.testing.assert_frame_equal(p, history.loc[p.index], check_exact=True)
            check("complete state prefix exact", True)
    check("no network attempts", not ATTEMPTS)
    check("source remains reviewed bytes", digest(SOURCE) == expected)
    refs = [SOURCE, OLD, design, HERE / "clock_method_review.json", Path(__file__)]
    result = dict(
        status="PASS",
        blocking_findings=[],
        reviewed_hashes={p.relative_to(ROOT).as_posix(): digest(p) for p in refs},
        checks=sum(COUNTS.values()),
        check_counts=dict(COUNTS),
        prepared=prep,
        prepared_content_hashes=identities,
        new_accounts=0,
        new_fits=0,
        new_data_preparations=0,
        new_return_labels=0,
        network_attempts=ATTEMPTS,
        scope="Two local source state histories and bounded synthetic clocks. No account cash returns or policy outcome choice, no raw market exports, no full old feature oracle.",
        limits=[
            "Funded fresh RETRY must be audited exact against EX044001 before new arm; local source equality does not substitute it.",
            "KEEP consumes planned opportunities even if hypothetical BUY would fail. No fake actual cycle or promise of original BASE clock recovery.",
            "All2020-25 development;2026 tail technical only, no economic outcome summarized by this reviewer.",
        ],
    )
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "checks": result["checks"],
                "review_sha256": digest(destination),
            }
        )
    )


if __name__ == "__main__":
    main()
