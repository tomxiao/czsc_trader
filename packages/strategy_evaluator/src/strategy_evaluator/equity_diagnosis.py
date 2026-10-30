"""US continuous-account decomposition, preserving event income and session units."""
from collections import defaultdict
from datetime import date
import math
import pandas as pd

from .account_diagnosis import (AccountDiagnosisCalculation, AccountDiagnosisStatus, AccountPnl,
                               AnnualPnl, DailyPnl, DailyPathComparison, CyclePathComparison)

PROTOCOL = "equity-continuous-account-v1"


def _timezone(ledger):
    rule = ledger['specification']['market']['rule_version']
    if rule == 'US_EQUITY_V1':
        return 'America/New_York'
    if rule == 'CN_EQUITY_V1':
        return 'Asia/Shanghai'
    raise ValueError('unknown market calendar in retained ledger')


def _session(stamp, timezone='America/New_York'):
    return pd.Timestamp(stamp).tz_convert(timezone).date().isoformat()


def _decompose(ledger, identity, start, end):
    rows = ledger["account_points"]
    if start < rows[0]["session"] or end > rows[-1]["session"]:
        raise ValueError("diagnostic window exceeds retained account coverage")
    timezone = _timezone(ledger)
    fills = defaultdict(list)
    for row in ledger['fills']:
        fills[pd.Timestamp(row['interval_end'])].append(row)
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
        # FIFO within an observation partitions exact PnL for scale-in/out and
        # same-observation closed/reopened cycles; it is not a price prediction.
        from collections import deque
        inventory = deque()
        if quantity:
            inventory.append([quantity, previous_close, 'holding'])
        executed = fills.get(stamp, ())
        for fill in executed:
            traded, price = int(fill['quantity']), float(fill['price'])
            fees -= float(fill['fees'])
            if fill['side'] == 'BUY':
                inventory.append([traded, price, 'entry'])
            else:
                remaining = traded
                while remaining:
                    if not inventory:
                        raise ValueError('diagnostic fill sells unheld units')
                    lot = inventory[0]
                    used = min(remaining, lot[0])
                    exit_pnl += used * (price - lot[1])
                    lot[0] -= used
                    remaining -= used
                    if not lot[0]:
                        inventory.popleft()
        for units, basis, origin in inventory:
            if origin == 'entry':
                entry += units * (close - basis)
            else:
                holding += units * (close - basis)
        change = float(row["equity"]) - previous_equity
        residual = change - math.fsum((entry, holding, exit_pnl, fees))
        if not math.isclose(residual, 0., rel_tol=1e-10, abs_tol=1e-7):
            raise ValueError("equity diagnosis does not reconcile")
        cycles = {fill['cycle_id'] for fill in executed}
        if row.get('cycle_id') is not None:
            cycles.add(row['cycle_id'])
        per_session[row['session']].append((previous_equity, float(row['equity']), entry, holding, exit_pnl, fees,
            next(iter(cycles)) if len(cycles) == 1 else None, row['decision_id'],
            tuple(fill['fill_id'] for fill in executed)))
        previous_equity, previous_close, quantity = float(row["equity"]), close, int(row["quantity"])
    daily = []
    for session, parts in sorted(per_session.items()):
        if not start <= session <= end:
            continue
        totals = [math.fsum(r[i] for r in parts) for i in range(2, 6)]
        cycles = {r[6] for r in parts if r[6] is not None}
        decisions = tuple(r[7] for r in parts)
        filled = tuple(identity for r in parts for identity in r[8])
        order_ids = tuple(x["order_id"] for x in ledger["orders"] if _session(x["valid_end"], timezone) == session)
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
    timezone = _timezone(baseline)
    def entries(ledger):
        exits = {r['cycle_id']: _session(r['exit_at'], timezone) for r in ledger['trades']}
        initial = {}
        for row in ledger['fills']:
            if row['side'] == 'BUY':
                initial.setdefault(row['cycle_id'], row)
        values, ordinal = {}, defaultdict(int)
        for row in initial.values():
            stamp, cycle = pd.Timestamp(row['interval_start']), row['cycle_id']
            if _session(stamp, timezone) <= end.isoformat() and exits.get(cycle, end.isoformat()) >= start.isoformat():
                key = (stamp, ordinal[stamp])
                ordinal[stamp] += 1
                values[key] = (cycle, exits.get(cycle))
        return values
    le, re = entries(baseline), entries(alternative)
    for key in sorted(le.keys() | re.keys()):
        timestamp = key[0]
        lc, lx = le.get(key, (None, None))
        rc, rx = re.get(key, (None, None))
        paths.append(CyclePathComparison(symbol, _session(timestamp, timezone), lc, rc,
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
