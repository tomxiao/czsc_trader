"""Independent EX035 economic audit. Read-only inputs; no account execution.

Public exports audit_control(account_json), audit_path(account_json, node) return
JSON-serializable PASS/FAIL summaries. ``node`` is an unchanged E9 inventory row.
References are authenticated once from published EX034 / C0011 evidence. No
identity hash is required to equal between different diagnostic runtimes.
"""

import csv
import io
import json
import math
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from numbers import Real
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef


ROOT = Path(__file__).resolve().parents[5]
IDENTITIES = {"decision_id", "order_id", "fill_id", "cycle_id"}
MONEY_FIELDS = {"cash", "cash_before", "equity", "fees"}
MONEY_EPS = 1e-7
VALUE_EPS = 1e-10


def day(value):
    return value[:10] if isinstance(value, str) else value


@lru_cache(maxsize=1)
def references():
    method = ROOT / "research/S014/materials/20261018_action_value_method_review/inventory.json"
    inv = json.loads(method.read_bytes())
    record = inv["sources"]["public_account_C0011"]
    ref = EvidenceRef.from_dict(record["public_ref"])
    raw = ref.resolve(ROOT).read_bytes()
    if sha256(raw).hexdigest() != ref.sha256 or ref.sha256 != record["sha256"]:
        raise ValueError("C0011 source authentication failed")
    original = json.loads(raw)
    if original["result_hash"] != record["result_hash"]:
        raise ValueError("C0011 result identity mismatch")
    old = ROOT / "research/S014/experiments/EX034_20261018"
    result = json.loads((old / "others/result.json").read_bytes())
    event_ref = EvidenceRef.from_dict(result["evidence"]["others/events.csv"])
    event_bytes = event_ref.resolve(ROOT).read_bytes()
    if sha256(event_bytes).hexdigest() != event_ref.sha256:
        raise ValueError("EX034 events authentication failed")
    if event_bytes != (old / "others/events.csv").read_bytes():
        raise ValueError("EX034 events local/public mismatch")
    events = {r["cycle_id"]: r for r in csv.DictReader(io.StringIO(event_bytes.decode()))}
    e9_path = ROOT / "research/S014/materials/20261018_e9_extension_review/inventory.json"
    e9 = json.loads(e9_path.read_bytes())
    nodes = {r["cycle_id"]: r for r in e9["events"]}
    return original, events, nodes


class Checks:
    def __init__(self):
        self.n = 0
        self.errors = []

    def require(self, condition, label):
        self.n += 1
        if not condition and len(self.errors) < 40:
            self.errors.append(label)

    def equal(self, actual, expected, label, key=""):
        if isinstance(actual, Real) and isinstance(expected, Real):
            eps = MONEY_EPS if key in MONEY_FIELDS else VALUE_EPS
            self.require(math.isfinite(actual) and math.isfinite(expected)
                         and abs(actual - expected) <= eps, label)
        else:
            self.require(actual == expected, label)

    def rows(self, actual, expected, label):
        self.require(len(actual) == len(expected), f"{label}: row count")
        for index, (a, e) in enumerate(zip(actual, expected)):
            for key in e.keys() - IDENTITIES:
                self.require(key in a, f"{label}[{index}].{key}: missing")
                if key in a:
                    self.equal(a[key], e[key], f"{label}[{index}].{key}", key)

    def result(self, kind, **extra):
        return {"status": "FAIL" if self.errors else "PASS", "kind": kind,
                "checks": self.n, "errors": self.errors,
                "money_absolute_tolerance": MONEY_EPS,
                "other_numeric_absolute_tolerance": VALUE_EPS,
                "identity_fields_excluded_from_cross_runtime_equality": sorted(IDENTITIES),
                **extra}


def _run(account, checks):
    checks.require(len(account["runs"]) == 1, "exactly one full-window account run")
    return account["runs"][0]


def _internal(run, c):
    """Check ID relationships separately and independently rebuild cash / shares."""
    ledgers = {name: table["data"] for name, table in run["ledgers"].items()}
    by = {}
    for name, field in (("decisions", "decision_id"), ("orders", "order_id"),
                        ("fills", "fill_id"), ("trades", "cycle_id")):
        rows = ledgers[name]
        by[name] = {r[field]: r for r in rows}
        c.require(len(by[name]) == len(rows), f"unique {name}.{field}")
    by_date = {}
    by_cycle = {}
    for f in ledgers["fills"]:
        by_date.setdefault(day(f["fill_time"]), []).append(f)
        by_cycle.setdefault(f["cycle_id"], []).append(f)
        order = by["orders"].get(f["order_id"])
        c.require(order is not None, "fill links to existing order")
        if order is not None:
            for field in ("cycle_id", "decision_id", "side", "quantity", "signal_date"):
                c.equal(f[field], order[field], f"fill/order {field}", field)
            c.equal(day(f["fill_time"]), day(order["execution_date"]), "fill/order execution date")
        c.require(f["cycle_id"] in by["trades"], "fill links to existing trade")
        c.equal(f["fees"], f["quantity"] * f["price"] * .001, "unchanged single-side fee", "fees")
        c.require(f["quantity"] > 0 and f["quantity"] % 100 == 0, "full lot quantity")
    for order in ledgers["orders"]:
        decision = by["decisions"].get(order["decision_id"])
        c.require(decision is not None, "order links to existing ledger decision")
        if decision is not None:
            c.equal(order["signal_date"], decision["signal_date"], "order/decision signal date")
    for trade in ledgers["trades"]:
        own = by_cycle.get(trade["cycle_id"], [])
        buy = [f for f in own if f["side"] == "BUY"]
        sell = [f for f in own if f["side"] == "SELL"]
        c.require(len(buy) == 1 and len(sell) <= 1, "one full buy and at most one full sale per cycle")
        for fills, prefix in ((buy, "entry"), (sell, "exit")):
            if fills:
                f = fills[0]
                for key in ("price", "date"):
                    value = f["price"] if key == "price" else f["fill_time"]
                    c.equal(trade[f"{prefix}_{key}"], value, f"trade/{prefix} fill {key}", key)
                c.equal(trade["quantity"], f["quantity"], "trade/fill quantity")
        c.equal(trade["status"], "CLOSED" if sell else "OPEN", "trade close status")
    previous_cash, previous_qty = 100000., 0
    for row in ledgers["account_daily"]:
        c.equal(row["cash_before"], previous_cash, "daily cash continuity", "cash")
        c.equal(row["quantity_before"], previous_qty, "daily share continuity")
        cash, quantity = previous_cash, previous_qty
        for f in by_date.get(day(row["date"]), []):
            direction = 1 if f["side"] == "BUY" else -1
            cash -= direction * f["price"] * f["quantity"] + f["fees"]
            quantity += direction * f["quantity"]
        c.equal(row["cash"], cash, "cash reconstructed from public fills", "cash")
        c.equal(row["quantity"], quantity, "shares reconstructed from public fills")
        c.equal(row["equity"], row["cash"] + row["quantity"] * row["close"], "closing wealth arithmetic", "equity")
        previous_cash, previous_qty = row["cash"], row["quantity"]
    c.require(len(ledgers["account_daily"]) == 1642, "unchanged 1642-session full window")
    return ledgers


def audit_control(account_json):
    """No-op must equal C0011 over all original economic and signal fields."""
    original, _, _ = references()
    c = Checks()
    run = _run(account_json, c)
    base = _run(original, c)
    ledgers = _internal(run, c)
    c.require(set(ledgers) == set(base["ledgers"]), "same public ledger families")
    for name, rows in ledgers.items():
        if name in base["ledgers"]:
            c.rows(rows, base["ledgers"][name]["data"], name)
    c.rows(run["signals"]["data"], base["signals"]["data"], "signals")
    c.require(not any(bool(r.get("intervention_today", False)) for r in ledgers["decisions"]),
              "no-op never intervenes")
    return c.result("NOOP_FULL_ACCOUNT_EQUIVALENCE", reference_result_hash=original["result_hash"])


def audit_path(account_json, node):
    """Audit fixed intervention, preserved prefix, exact E6 sale and H3 resumption."""
    original, old_events, nodes = references()
    c = Checks()
    c.require(node == nodes.get(node["cycle_id"]), "node exactly equals fixed E9 inventory")
    c.require(node["eligible"] and node["route"] == "PUBLIC_H_REPLAY_REQUIRED", "authorized replay node")
    old = old_events[node["cycle_id"]]
    d, e6 = node["E2"], node["E6"]
    run = _run(account_json, c)
    ledgers = _internal(run, c)
    baseline = original["runs"][0]
    base = {k: v["data"] for k, v in baseline["ledgers"].items()}
    for name, date_key, inclusive in (("account_daily", "date", True),
                                     ("fills", "fill_time", True),
                                     ("orders", "execution_date", True),
                                     ("decisions", "signal_date", False)):
        def prefix(rows):
            return [r for r in rows if day(r[date_key]) <= d] if inclusive else [r for r in rows if day(r[date_key]) < d]
        c.rows(prefix(ledgers[name]), prefix(base[name]), f"prefix {name}")
    c.rows([s for s in run["signals"]["data"] if day(s["signal_date"]) < d],
           [s for s in baseline["signals"]["data"] if day(s["signal_date"]) < d], "prefix signals")
    c.rows([t for t in ledgers["trades"] if t["exit_date"] and day(t["exit_date"]) < d],
           [t for t in base["trades"] if t["exit_date"] and day(t["exit_date"]) < d], "prefix closed trades")
    daily = {day(r["date"]): r for r in ledgers["account_daily"]}
    for field, source in (("cash", "D_cash"), ("quantity", "D_quantity"), ("equity", "W_D")):
        c.equal(daily[d][field], float(old[source]), f"D {field} vs EX034", field)
    interventions = [r for r in ledgers["decisions"] if bool(r.get("intervention_today", False))]
    c.require(len(interventions) == 1, "exactly one intervention")
    if interventions:
        c.equal(day(interventions[0]["signal_date"]), d, "intervention at E2 close")
        c.equal(interventions[0]["holding_horizon"], 6, "intervention extends to H6")
        c.equal(interventions[0]["target_position"], 1, "retain original holding on D")
    own = [t for t in ledgers["trades"] if day(t["entry_date"]) == node["entry_date"]]
    c.require(len(own) == 1, "exact original entry remains unique")
    if own:
        trade = own[0]
        original_trade = next(t for t in base["trades"] if t["cycle_id"] == node["cycle_id"])
        for field in ("entry_date", "entry_price", "quantity"):
            c.equal(trade[field], original_trade[field], f"original trade {field}", field)
        c.equal(day(trade["exit_date"]), e6, "old holding sold at E6")
        c.equal(trade["exit_price"], float(old["H_sell_price"]), "E6 sale price", "price")
        sells = [f for f in ledgers["fills"] if f["cycle_id"] == trade["cycle_id"] and f["side"] == "SELL"]
        c.require(len(sells) == 1, "old holding one full sale")
        if sells:
            c.equal(sells[0]["fees"], float(old["H_sell_fee"]), "E6 sale fee", "fees")
    c.equal(daily[e6]["quantity"], 0, "E6 oldholding sale leaves cash")
    c.equal(daily[e6]["cash"], float(old["H_T"]), "E6 H cash equals EX034", "cash")
    for row in ledgers["decisions"]:
        if day(row["signal_date"]) >= e6:
            c.require(row["holding_horizon"] in (0, 3), "post-sale horizons resume H3")
    c.require(node["E9"] in daily, "fixed E9 endpoint present")
    return c.result("ONE_E2_INTERVENTION_ACCOUNT", cycle_id=node["cycle_id"],
                    entry_date=node["entry_date"], decision_date=d, E6=e6, E9=node["E9"])


def selfcheck():
    """Tamper detection on existing reference copies; never evaluates accounts."""
    original, _, _ = references()
    checks = {"reference_control": audit_control(original)["status"] == "PASS"}
    mutations = {
        "cash_tamper": lambda a: a["runs"][0]["ledgers"]["account_daily"]["data"][0].update(cash=99999.),
        "signal_tamper": lambda a: a["runs"][0]["signals"]["data"][0].update(target_position=1),
        "link_tamper": lambda a: a["runs"][0]["ledgers"]["fills"]["data"][0].update(order_id="BROKEN"),
        "fee_tamper": lambda a: a["runs"][0]["ledgers"]["fills"]["data"][0].update(fees=0),
    }
    for name, mutate in mutations.items():
        account = deepcopy(original)
        mutate(account)
        checks[name] = audit_control(account)["status"] == "FAIL"
    # Changing identity labels consistently is harmless; corrupting linkage is not.
    account = deepcopy(original)
    for table in list(account["runs"][0]["ledgers"].values()) + [account["runs"][0]["signals"]]:
        for row in table["data"]:
            for key in IDENTITIES & row.keys():
                row[key] = "DIAGNOSTIC-" + row[key] if row[key] is not None else None
    checks["consistent_identity_relabel"] = audit_control(account)["status"] == "PASS"
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "new_account_evaluations": 0}


if __name__ == "__main__":
    print(json.dumps(selfcheck(), ensure_ascii=False, indent=2))
