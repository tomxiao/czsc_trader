"""Bounded independent EX044 state audit; no accounts, returns or feature re-oracle."""

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

sys.dont_write_bytecode = True
ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
SOURCE = (
    ROOT
    / "research/S014/experiments/EX044_20261019/src/strategy_runtime/strategies/action_role_review.py"
)
OLD = (
    ROOT
    / "research/S014/experiments/EX043_20261019/src/strategy_runtime/strategies/exante_hold_exit.py"
)
DESIGN = HERE.parent / "design_decision.json"
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
    raise RuntimeError("Offline authenticated PreparedDataRef only")


def synthetic(code, parameters):
    days = pd.bdate_range("2020-01-02", periods=85)
    market = pd.DataFrame(
        {"Date": days, "Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0}
    )
    limits = pd.DataFrame({"Date": days, "DownLimit": 80.0, "UpLimit": 120.0})
    status = pd.DataFrame({"Date": days, "Status": "TRADING"})
    template = code.causal_features(market)
    template.loc[:, "z5"] = 0.0
    template.loc[:, "shock_known"] = True
    template.loc[:, "atr20_prior"] = 1.0
    template.loc[:, "atr_positive"] = True
    original = code.causal_features

    def run(features=None, frame=None, states=None):
        f = template if features is None else features
        code.causal_features = lambda prices: f.loc[pd.to_datetime(prices.Date)].copy()
        m = market if frame is None else frame
        try:
            return code.history(
                m,
                m.copy(),
                limits,
                status if states is None else states,
                code.ActionRoleConfig.parse(parameters),
            )
        finally:
            code.causal_features = original

    return days, market, status, template, run


def toys(code, params):
    _, _, _, f, run = synthetic(code, params[1])
    f.iloc[59, f.columns.get_loc("z5")] = 2.0
    equal = run(f)
    check("gate Z equality permits original BUY", equal.iloc[59].entry_signal == 1)
    f.iloc[59, f.columns.get_loc("z5")] = np.nextafter(2.0, np.inf)
    blocked = run(f)
    check(
        "gate blocks no intent anchor reservation",
        blocked.iloc[59].entry_guard_blocked == 1
        and blocked.iloc[59].entry_signal == 0
        and blocked.iloc[59].reservation_index == -1
        and blocked.iloc[59].entry_index == -1,
    )
    check(
        "blocked gate retries next D no fake failed BUY",
        blocked.iloc[60].entry_signal == 1
        and blocked.iloc[60].failed_buy_reset == 0
        and blocked.iloc[60].reservation_index == -1,
    )
    f.iloc[59, f.columns.get_loc("shock_known")] = False
    check("unknown Z does not block", run(f).iloc[59].entry_signal == 1)
    _, market, _, f, run = synthetic(code, params[1])
    market.loc[60, ["Open", "High", "Low", "Close"]] = [104.0, 104.0, 103.0, 103.0]
    failed = run(frame=market)
    check(
        "real unfilled BUY retains original failed reset",
        failed.iloc[60].failed_buy_reset == 1
        and failed.iloc[60].entry_signal == 0
        and failed.iloc[60].held_at_close == 0
        and failed.iloc[60].reservation_index == -1,
    )
    _, _, _, f, run = synthetic(code, params[2])
    f.iloc[60, f.columns.get_loc("z5")] = 3.0
    anyp = run(f)
    check(
        "ANY_P actual fill negative NET P permits next E risk",
        anyp.iloc[60].buy_filled_today == 1
        and anyp.iloc[60].net_profit < 0
        and anyp.iloc[60].selected_profit_exit == 0
        and anyp.iloc[60].selected_shock_exit == 1
        and anyp.iloc[60].target_position == 0
        and anyp.iloc[60].sell_filled_today == 0
        and anyp.iloc[61].sell_filled_today == 1,
    )
    _, _, _, f, run = synthetic(code, params[4])
    loss = 100.0 * 1.001 - 100.0 * 0.999
    f.loc[:, "atr20_prior"] = loss
    equal = run(f)
    check(
        "NET cost inclusive boundary and Tplus1",
        equal.iloc[60].selected_cost_exit == 1
        and equal.iloc[60].buy_filled_today == 1
        and equal.iloc[60].sell_filled_today == 0
        and equal.iloc[61].sell_filled_today == 1,
    )
    f.loc[:, "atr20_prior"] = np.nextafter(loss, np.inf)
    check("cost just below threshold does not trigger", run(f).iloc[60].selected_cost_exit == 0)
    f.iloc[61, f.columns.get_loc("atr20_prior")] = loss
    shrink = run(f)
    check(
        "dynamic ATR shrink can trigger unchanged close",
        shrink.iloc[60].selected_cost_exit == 0 and shrink.iloc[61].selected_cost_exit == 1,
    )
    _, market, status, f, run = synthetic(code, params[4])
    f.iloc[60, f.columns.get_loc("atr20_prior")] = loss
    status.loc[61, "Status"] = "SUSPENDED"
    pending = run(f, states=status)
    check(
        "blocked sell inherited priority suppresses new risk",
        pending.iloc[61].held_at_close == 1
        and pending.iloc[61].pending_inherited == 1
        and pending.iloc[61].selected_cost_exit == 0
        and pending.iloc[61].exit_pending == 1
        and pending.iloc[62].sell_filled_today == 1,
    )
    check(
        "reservation survives actual early sale",
        pending.iloc[62].reservation_index == 70 and pending.iloc[62].entry_signal == 0,
    )
    check("reservation original retry date", pending.iloc[70].entry_signal == 1)


def main():
    expected = sys.argv[1]
    destination = HERE / "source_state_review.json"
    if destination.exists():
        raise FileExistsError(destination)
    check("stable source expected hash", digest(SOURCE) == expected)
    check(
        "locked design hash",
        digest(DESIGN) == "64fadefd74eb267e173a14a1c747d6607c6630d3bf5c7c98755177a63f784846",
    )
    check(
        "original source frozen hash",
        digest(OLD) == "e980a552367e9354a5f2fcfcd411e5c6a64a408ecb83bed115aa9b578029e57a",
    )
    design = json.loads(DESIGN.read_bytes())
    parameters = design["fixed_parameters"]
    trees = [ast.parse(p.read_text(encoding="utf-8")) for p in [SOURCE, OLD]]
    for name in [
        "causal_features",
        "tick",
        "buy_limit",
        "calendar_request",
        "derive_calculation_scope",
    ]:
        nodes = [
            next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name)
            for t in trees
        ]
        check("unchanged AST " + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
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
        check("unchanged contract AST " + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    code, old = load(SOURCE, "independent_role_source"), load(OLD, "independent_role_prior")
    for p in parameters:
        check("five configs valid", bool(code.ActionRoleConfig.parse(p)))
    invalid = [
        dict(parameters[4], entry_guard="BLOCK_SHOCK"),
        dict(parameters[4], exit_domain="ANY_P"),
        dict(parameters[0], unknown="x"),
        dict(parameters[0], cost_stop=True),
    ]
    for p in invalid:
        try:
            code.ActionRoleConfig.parse(p)
        except ValueError:
            check("unplanned config rejected", True)
        else:
            raise AssertionError("unplanned config accepted")
    toys(code, parameters)
    requests.sessions.Session.request = prohibit
    socket.socket.connect = prohibit
    socket.create_connection = prohibit
    ref_record = json.loads(
        (
            ROOT / "research/S014/experiments/EX040_20261019/others/accounts/run-003.json"
        ).read_bytes()
    )
    ref = EvidenceRef.from_dict(ref_record["binding_ref"])
    check("same S014 public evidence", ref.experiment.strategy_id == "S014")
    content = ref.resolve(ROOT).read_bytes()
    check("public binding byte hash", sha256(content).hexdigest() == ref.sha256)
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
            "same prepared content hash",
            fetched.ready
            and fetched.identity.content_sha256 == binding["execution_identities"][key],
        )
        frames[name] = fetched.dataframe.sort_values("Date").reset_index(drop=True)
        identities[name] = fetched.identity.content_sha256
    histories = []
    for p in parameters:
        h = code.history(**frames, config=code.ActionRoleConfig.parse(p))
        histories.append(h)
        prior_pending = False
        for i, row in enumerate(h.itertuples()):
            inherited = bool(prior_pending and row.held_at_close and not row.sell_filled_today)
            eligible = bool(row.held_at_close and not inherited and i < row.deadline_index)
            accel = bool(eligible and row.shock_known and row.z5 > 2)
            shock = bool(accel and (p["exit_domain"] == "ANY_P" or row.net_profit > 0))
            cost = bool(eligible and row.atr_positive and row.cost_loss_price >= row.atr20_prior)
            cost = bool(cost and p["cost_stop"] == "NET_LOSS_1ATR")
            check(
                "new state predicates and priority",
                row.profit_exit_eligible == eligible
                and row.pending_inherited == inherited
                and row.selected_shock_exit == shock
                and row.selected_cost_exit == cost
                and row.selected_risk_exit == (shock or cost),
            )
            if row.held_at_close:
                loss = row.entry_fill_price * 1.001 - float(frames["market"].iloc[i].Close) * 0.999
                check("net cost units exact", row.cost_loss_price == loss)
                check(
                    "held pending priority exact",
                    bool(row.exit_pending)
                    == bool(
                        inherited or row.deadline_exit or shock or cost or row.ordinary_support_exit
                    ),
                )
                check(
                    "risk overrides entry grace", not (row.entry_grace_applied and (shock or cost))
                )
            if row.entry_guard_blocked:
                previous_reserve = h.iloc[i - 1].reservation_index if i else -1
                check(
                    "blocked gate no fake trade or anchor",
                    row.original_entry_candidate == 1
                    and row.candidate_shock == 1
                    and row.entry_signal == 0
                    and row.target_position == 0
                    and row.held_at_close == 0
                    and row.failed_buy_reset == 0
                    and row.entry_index == -1
                    and row.reservation_index == previous_reserve,
                )
            check(
                "candidate gate exact",
                bool(row.entry_signal)
                == bool(row.original_entry_candidate and not row.entry_guard_blocked),
            )
            check(
                "gate current D only",
                bool(row.entry_guard_blocked)
                == bool(
                    row.original_entry_candidate
                    and row.shock_known
                    and row.z5 > 2
                    and p["entry_guard"] == "BLOCK_SHOCK"
                ),
            )
            prior_pending = bool(row.exit_pending)
        for cutoff in ["2024-10-09", "2025-12-31"]:
            prefix = {
                k: v.loc[pd.to_datetime(v.Date) <= pd.Timestamp(cutoff)].copy()
                for k, v in frames.items()
            }
            recomputed = code.history(**prefix, config=code.ActionRoleConfig.parse(p))
            pd.testing.assert_frame_equal(recomputed, h.loc[recomputed.index], check_exact=True)
            check("full history prefix exact", True)
    prior = old.history(
        **frames,
        config=old.HoldExitConfig.parse({"hold_rule": "ENTRY_GRACE", "exit_rule": "SHOCK_PROFIT"}),
    )
    pd.testing.assert_frame_equal(histories[0][prior.columns], prior, check_exact=True)
    check("new NOOP source history full old state exact", True)
    check("zero network attempts", not ATTEMPTS)
    check("source stable through audit", digest(SOURCE) == expected)
    refs = [
        SOURCE,
        OLD,
        DESIGN,
        Path(__file__),
        HERE / "method_adversarial_review.json",
        ROOT
        / "research/S014/materials/20261019_exante_hold_exit/official/method_observability_audit.json",
    ]
    result = {
        "status": "PASS",
        "blocking_findings": [],
        "reviewed_hashes": {p.relative_to(ROOT).as_posix(): digest(p) for p in refs},
        "checks": sum(COUNTS.values()),
        "check_counts": dict(COUNTS),
        "prepared": prep,
        "prepared_content_hashes": identities,
        "public_binding_ref": ref_record["binding_ref"],
        "network_attempts": ATTEMPTS,
        "new_accounts": 0,
        "new_fits": 0,
        "new_return_labels": 0,
        "new_data_preparations": 0,
        "scope": "Five local source histories with original authenticated prepared inputs; independent new predicates, unchanged feature/contract AST, exact baseline old states, two prefix cutoffs and bounded synthetic boundaries. No cash account or policy economic outcomes computed; raw market inputs remain in memory. No repetition of prior full feature oracle.",
        "limitations": [
            "Source history NOOP exactness is not a funded account acceptance. A must independently audit fresh EX044 NOOP and all funded arms.",
            "Dynamic ATR can create a cost crossing without a new decline; not filtered retrospectively.",
            "D-close net-loss trigger cannot remove incurred entry-day damage or guarantee next-E fills/prices.",
            "Eligibility/trigger counts and economic outcomes remain for the later actual-account interpretation; no policy selection here.",
        ],
    }
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "checks": result["checks"],
                "source_sha256": expected,
                "review_sha256": digest(destination),
            }
        )
    )


if __name__ == "__main__":
    main()
