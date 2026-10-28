"""US continuous-account decomposition, preserving event income and session units."""
from collections import defaultdict
from datetime import date
import math
import pandas as pd

from .account_diagnosis import (AccountDiagnosisCalculation, AccountDiagnosisStatus, AccountPnl,
                               AnnualPnl, DailyPnl, DailyPathComparison, CyclePathComparison)

PROTOCOL = "equity-continuous-account-v1"


def _session(stamp):
    return pd.Timestamp(stamp).tz_convert("America/New_York").date().isoformat()


def _decompose(ledger, identity, start, end):
    rows = ledger["account_points"]
    if start < rows[0]["session"] or end > rows[-1]["session"]:
        raise ValueError("diagnostic window exceeds retained account coverage")
    fills = {pd.Timestamp(x["interval_end"]): x for x in ledger["fills"]}
    if len(fills) != len(ledger["fills"]):
        raise ValueError("duplicate equity execution intervals")
    events = sorted(ledger["actions"], key=lambda x: (x["account_revision"], pd.Timestamp(x["time"])))
    splits = {x["EventId"]: float(x["Ratio"]) for x in ledger["action_facts"] if x["Kind"] == "SPLIT"}
    previous_equity, previous_close, quantity, cursor = ledger["initial_cash"], None, 0, 0
    per_session = defaultdict(list)
    for row in rows:
        stamp, close = pd.Timestamp(row["time"]), float(row["close"])
        entry = holding = exit_pnl = fees = 0.
        # Adjacent bars share a boundary timestamp. Events effective at the next
        # open belong to its revision, not to the preceding close observation.
        while cursor < len(events) and events[cursor]["account_revision"] <= row["account_revision"]:
            event = events[cursor]
            if event["kind"] == "SPLIT":
                ratio = splits[event["event_id"]]
                quantity = int(quantity * ratio)
                if previous_close is not None:
                    previous_close /= ratio
            elif event["kind"] == "CASH_DIVIDEND":
                holding += float(event["amount"])
            # Payment and sale settlement transfer accounts; they are not new income.
            cursor += 1
        fill = fills.get(stamp)
        if fill is not None:
            traded, price = int(fill["quantity"]), float(fill["price"])
            fees = -float(fill["fees"])
            if fill["side"] == "BUY":
                entry = traded * (close - price)
                if quantity:
                    holding += quantity * (close - previous_close)
            else:
                exit_pnl = traded * (price - previous_close)
                holding += (quantity - traded) * (close - previous_close)
        elif quantity:
            holding += quantity * (close - previous_close)
        change = float(row["equity"]) - previous_equity
        residual = change - math.fsum((entry, holding, exit_pnl, fees))
        if not math.isclose(residual, 0., rel_tol=1e-10, abs_tol=1e-7):
            raise ValueError("equity diagnosis does not reconcile")
        per_session[row["session"]].append((previous_equity, float(row["equity"]), entry, holding, exit_pnl, fees,
                                            row.get("cycle_id") or (None if fill is None else fill["cycle_id"]),
                                            row["decision_id"], None if fill is None else fill["fill_id"]))
        previous_equity, previous_close, quantity = float(row["equity"]), close, int(row["quantity"])
    daily = []
    for session, parts in sorted(per_session.items()):
        if not start <= session <= end:
            continue
        totals = [math.fsum(r[i] for r in parts) for i in range(2, 6)]
        cycles = {r[6] for r in parts if r[6] is not None}
        decisions = tuple(r[7] for r in parts)
        filled = tuple(r[8] for r in parts if r[8] is not None)
        order_ids = tuple(x["order_id"] for x in ledger["orders"] if _session(x["valid_end"]) == session)
        delta = parts[-1][1] - parts[0][0]
        daily.append(DailyPnl(session, parts[0][0], parts[-1][1], *totals, delta, delta - math.fsum(totals),
                              next(iter(cycles)) if len(cycles) == 1 else None, decisions, order_ids, filled))
    if not daily:
        raise ValueError("diagnostic window has no retained sessions")
    annual = []
    for year in sorted({int(x.session[:4]) for x in daily}):
        selected = [x for x in daily if int(x.session[:4]) == year]
        opening, closing = selected[0].opening_equity, selected[-1].closing_equity
        parts = [math.fsum(getattr(x, k) for x in selected) for k in ("entry", "holding", "exit", "fees")]
        annual.append(AnnualPnl(year, selected[0].session, selected[-1].session,
            start > f"{year}-01-01" or end < f"{year}-12-31" or rows[0]["session"] > f"{year}-01-01" or rows[-1]["session"] < f"{year}-12-31",
            opening, closing, *parts, closing - opening, closing - opening - math.fsum(parts),
            *(p / opening if opening > 0 else None for p in parts)))
    return AccountPnl(identity, tuple(daily), tuple(annual))


def diagnose_equity_accounts(baseline, baseline_id, start: date, end: date, *, symbol,
                             alternative=None, alternative_id=None):
    """Consume independently certified ledgers; no price/provider/strategy calls."""
    if type(start) is not date or type(end) is not date or start > end:
        raise ValueError("diagnosis requires ordered session dates")
    left = _decompose(baseline, baseline_id, start.isoformat(), end.isoformat())
    if alternative is None:
        return AccountDiagnosisCalculation(AccountDiagnosisStatus.COMPUTED, PROTOCOL, (), (left,))
    right = _decompose(alternative, alternative_id, start.isoformat(), end.isoformat())
    if tuple(x.session for x in left.daily) != tuple(x.session for x in right.daily):
        return AccountDiagnosisCalculation(AccountDiagnosisStatus.INCOMPARABLE, PROTOCOL, ("session coverage differs",))
    paths = []
    def entries(ledger):
        exits = {r["cycle_id"]: _session(r["exit_at"]) for r in ledger["trades"]}
        return {pd.Timestamp(r["interval_start"]): (r["cycle_id"], exits.get(r["cycle_id"]))
                for r in ledger["fills"] if r["side"] == "BUY"
                and _session(r["interval_start"]) <= end.isoformat()
                and exits.get(r["cycle_id"], end.isoformat()) >= start.isoformat()}
    le, re = entries(baseline), entries(alternative)
    for timestamp in sorted(le.keys() | re.keys()):
        lc, lx = le.get(timestamp, (None, None))
        rc, rx = re.get(timestamp, (None, None))
        paths.append(CyclePathComparison(symbol, _session(timestamp), lc, rc,
            lx if lx and lx <= end.isoformat() else None, rx if rx and rx <= end.isoformat() else None))
    def daily(ledger):
        result = {}
        for row in ledger["account_points"]:
            result[row["session"]] = row
        return result
    ld, rd = daily(baseline), daily(alternative)
    daily_paths = tuple(DailyPathComparison(x.session, ld[x.session]["cash"], rd[x.session]["cash"],
        ld[x.session]["quantity"], rd[x.session]["quantity"], ld[x.session]["equity"], rd[x.session]["equity"],
        rd[x.session]["equity"] - ld[x.session]["equity"]) for x in left.daily)
    return AccountDiagnosisCalculation(AccountDiagnosisStatus.COMPUTED, PROTOCOL, (), (left, right), tuple(paths), daily_paths)
