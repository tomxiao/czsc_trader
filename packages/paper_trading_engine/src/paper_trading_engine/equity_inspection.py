"""Recorded channel scenarios exercising normal durable US account components."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json

from dataflows import TimeInterval
from strategy_runtime.inspection import InspectionEnvironment
from .inspection_contracts import Record, _case_id, _money, _time
from .equity_contracts import EquityAccountRules, EquityOrderReport, EQUITY_OFFLINE_CHANNEL_ID
from .equity_advice import EquityAdviceClient, prepare_equity_decision
from .equity_execution import EquityExecution
from .broker import BrokerOrder, BrokerOrderRejectedError, BrokerSubmissionUncertainError
from .account_engine import AccountEngine
from .store import PaperStore


@dataclass(frozen=True)
class EquityPteDecision(Record):
    interval: TimeInterval
    at: datetime
    outcome: str = "ACCEPTED"
    expected: str = "SUBMITTED"

    def __post_init__(self):
        if type(self.interval) is not TimeInterval:
            raise TypeError("equity decision requires TimeInterval")
        _time(self.at)
        if self.outcome not in {"ACCEPTED", "REJECTED", "UNKNOWN"} or self.expected not in {
                "SUBMITTED", "NO_ORDER", "REJECTED", "UNKNOWN", "EXPIRED", "RECONCILIATION_BLOCKED"}:
            raise ValueError("invalid equity submission scenario")


@dataclass(frozen=True)
class EquityPteReport(Record):
    order_index: int
    cumulative_quantity: int
    average_price: Decimal
    at: datetime
    status: str
    settlement_at: datetime | None = None

    def __post_init__(self):
        if type(self.order_index) is not int or self.order_index < 0:
            raise ValueError("report requires nonnegative order index")
        EquityOrderReport("recorded", self.cumulative_quantity, self.average_price, self.at, self.status, self.settlement_at)


@dataclass(frozen=True)
class EquityPteRestart(Record):
    pass


@dataclass(frozen=True)
class EquityPteReconcile(Record):
    cash: Decimal
    quantity: int

    def __post_init__(self):
        _money(self.cash)
        if type(self.quantity) is not int or self.quantity < 0:
            raise ValueError("invalid equity snapshot quantity")


@dataclass(frozen=True)
class EquityPteAction(Record):
    event_id: str
    kind: str
    effective_at: datetime
    available_at: datetime
    source_sha256: str
    ratio: Decimal | None = None
    cash_per_share: Decimal | None = None
    pay_at: datetime | None = None

    def __post_init__(self):
        from .inspection_contracts import _hash, _id
        _id(self.event_id)
        _hash(self.source_sha256)
        _time(self.effective_at)
        _time(self.available_at)
        if self.kind not in {"SPLIT", "CASH_DIVIDEND"}:
            raise ValueError("invalid equity action")


@dataclass(frozen=True)
class EquityPteSettle(Record):
    at: datetime

    def __post_init__(self):
        _time(self.at)


EquityPteStep = EquityPteDecision | EquityPteReport | EquityPteRestart | EquityPteReconcile | EquityPteAction | EquityPteSettle


@dataclass(frozen=True)
class EquityPteScenario(Record):
    case_id: str
    steps: tuple[EquityPteStep, ...]
    expected_cash: Decimal
    expected_quantity: int
    expected_receivable: Decimal

    def __post_init__(self):
        _case_id(self.case_id)
        if type(self.steps) is not tuple or not self.steps or any(type(s) not in (
                EquityPteDecision, EquityPteReport, EquityPteRestart, EquityPteReconcile, EquityPteAction, EquityPteSettle) for s in self.steps):
            raise TypeError("scenario requires typed equity steps")
        _money(self.expected_cash)
        _money(self.expected_receivable)
        if type(self.expected_quantity) is not int or self.expected_quantity < 0:
            raise ValueError("invalid expected equity quantity")


@dataclass(frozen=True)
class EquityPteInspectionProtocol(Record):
    environment: InspectionEnvironment
    scenarios: tuple[EquityPteScenario, ...]

    def __post_init__(self):
        if type(self.environment) is not InspectionEnvironment:
            raise TypeError("equity inspection requires environment identity")
        if type(self.scenarios) is not tuple or not self.scenarios or any(type(s) is not EquityPteScenario for s in self.scenarios):
            raise TypeError("equity inspection requires typed scenarios")
        if len({s.case_id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("duplicate equity scenario")


class _RecordedChannel:
    channel_id = EQUITY_OFFLINE_CHANNEL_ID
    outcome = "ACCEPTED"

    def place_order(self, intent):
        if self.outcome == "REJECTED":
            raise BrokerOrderRejectedError("recorded channel rejection")
        if self.outcome == "UNKNOWN":
            raise BrokerSubmissionUncertainError("recorded missing channel acknowledgement")
        return BrokerOrder("recorded-" + intent.intent_id, intent.symbol, intent.side, intent.quantity,
                           intent.limit_price, "SUBMITTED", 0, 0., intent.intent_id, order_type=intent.order_type)


def _facts(store):
    account = store.virtual_account("equity")
    return {"initial_cash": account["initial_cash"], "account": {k: account[k] for k in ("cash", "frozen_cash", "quantity", "average_cost", "receivable", "realized_pnl", "total_assets")},
            "decisions": store.account_decisions("equity"), "orders": store.account_orders("equity"),
            "intents": store.account_intents("equity"),
            "fills": [dict(r) for r in store._connection.execute("SELECT * FROM fills WHERE account_id='equity' ORDER BY rowid")],
            "ledger": [dict(r) for r in store._connection.execute("SELECT * FROM account_ledger WHERE account_id='equity' ORDER BY rowid")],
            "events": [dict(r) for r in store._connection.execute("SELECT * FROM equity_account_events WHERE account_id='equity' ORDER BY event_id")]}


def inspect_equity_release(*, candidate, dataflows, binding, requests, initial_cash, fee_rate, permit, protocol, control=None):
    """Consume explicit channel facts; never infer fills from a historical price bar."""
    if type(protocol) is not EquityPteInspectionProtocol:
        raise TypeError("equity inspection requires explicit channel protocol")
    candidate.verify()
    from strategy_runtime.deployment import validate_release_package
    verified = validate_release_package(permit.isolated_repository / "strategies", permit.release_id)
    permit.validate_release(verified.release.release_id, verified.release.release_hash)
    if (verified.package_sha256 != permit.package_sha256 or candidate.source_root.resolve() != verified.source_root.resolve()
            or candidate.definition.to_dict() != dict(verified.release.payload["equity_definition"])):
        raise ValueError("equity inspection candidate differs from authenticated frozen package")
    from time import monotonic
    started = monotonic()
    def checkpoint():
        if control is not None:
            if control.cancelled is not None and control.cancelled():
                raise InterruptedError("equity inspection cancelled")
            if control.timeout_seconds is not None and monotonic() - started >= control.timeout_seconds:
                raise TimeoutError("equity inspection deadline reached")
    from strategy_runtime.inspection import collect_inspection_environment
    if collect_inspection_environment(permit.isolated_repository) != protocol.environment:
        raise ValueError("equity inspection environment differs from executing installation")
    cases, coverage = [], set()
    for scenario in protocol.scenarios:
        checkpoint()
        path = permit.validate_path(permit.workspace / "equity-pte" / scenario.case_id / "paper.db")
        if path.exists():
            raise ValueError("equity scenario database already exists")
        store = PaperStore(path, inspection_permit=permit)
        observed = []
        local_coverage = set()
        try:
            store.set_setting("futu_capital_pool", str(initial_cash))
            release_record = json.loads((permit.isolated_repository / "strategies" / candidate.strategy_id /
                "versions" / (verified.release.version + ".json")).read_text(encoding="utf-8"))
            store.create_virtual_account("equity", "Isolated US inspection", "inspection", permit.release_sha256,
                initial_cash, symbol=candidate.instrument.symbol, asset_type="stock", strategy_id=candidate.strategy_id,
                strategy_name_snapshot="Isolated US inspection", strategy_version=permit.release_id.split("-")[1],
                release_hash=permit.release_sha256, qualification_snapshot="INSPECTION", selection_data_cutoff=release_record["selection_data_cutoff"],
                channel_id=EQUITY_OFFLINE_CHANNEL_ID, equity_rules=EquityAccountRules(candidate.instrument, candidate.definition.execution_spec))
            store.set_virtual_paused("equity", False)
            channel = _RecordedChannel()
            orders, reports = [], set()
            now = None
            for step in scenario.steps:
                checkpoint()
                if type(step) is EquityPteRestart:
                    before = _facts(store)
                    store.close()
                    store = PaperStore(path, inspection_permit=permit)
                    if _facts(store) != before:
                        raise ValueError("reopened equity account differs from durable state")
                    local_coverage.add("RESTART")
                    observed.append({"kind": "RESTART", "before": before, "after": _facts(store)})
                    continue
                execution = EquityExecution(store, channel, now=lambda: now)
                if type(step) is EquityPteReconcile:
                    try:
                        execution.reconcile(cash=step.cash, quantity=step.quantity, account_id="equity")
                        observed.append({"kind": "RECONCILE", "status": "OK"})
                    except ValueError:
                        local_coverage.add("RECONCILIATION_BLOCKED")
                        observed.append({"kind": "RECONCILE", "status": "BLOCKED"})
                elif type(step) is EquityPteDecision:
                    now, channel.outcome = step.at, step.outcome
                    prepared = prepare_equity_decision(dataflows, candidate, binding, requests, step.interval, fee_rate=fee_rate)
                    try:
                        AccountEngine(store, EquityAdviceClient(store), now=lambda: now).refresh_account("equity", prepared=prepared)
                        ids = execution.submit_pending("equity")
                        orders.extend(ids)
                        actual = "SUBMITTED" if ids else "NO_ORDER"
                    except BrokerOrderRejectedError:
                        actual = "REJECTED"
                    except BrokerSubmissionUncertainError:
                        actual = "UNKNOWN"
                    except ValueError:
                        if not step.interval.start <= now < step.interval.end:
                            actual = "EXPIRED"
                        elif store._setting("channel_reconciliation_status") != "OK":
                            actual = "RECONCILIATION_BLOCKED"
                        else:
                            raise
                    if actual != step.expected:
                        raise ValueError(f"expected {step.expected}, observed {actual}")
                    local_coverage.add(actual)
                    observed.append({"kind": "DECISION", "outcome": actual, "interval": step.interval.to_dict() if hasattr(step.interval, "to_dict") else {"start":step.interval.start.isoformat(),"end":step.interval.end.isoformat()}})
                elif type(step) is EquityPteReport:
                    report = EquityOrderReport(orders[step.order_index], step.cumulative_quantity, step.average_price, step.at, step.status, step.settlement_at)
                    before = _facts(store)
                    execution.apply_report(report)
                    key = json.dumps(step.to_dict(), sort_keys=True)
                    if key in reports:
                        if _facts(store)["account"] != before["account"] or len(_facts(store)["fills"]) != len(before["fills"]):
                            raise ValueError("duplicate channel report changed account")
                        local_coverage.add("DUPLICATE")
                    reports.add(key)
                    if step.status == "FILLED_PART":
                        local_coverage.add("PARTIAL")
                    if step.status == "FILLED_ALL":
                        local_coverage.add("COMPLETED")
                    observed.append({"kind": "REPORT", "channel_order_id": report.channel_order_id, **step.to_dict()})
                elif type(step) is EquityPteAction:
                    from dataclasses import asdict
                    action_query, = (q for q in requests if q.parameters.query.product.name == "ACTIONS")
                    source = dataflows.fetch(action_query, prepared=binding.prepared)
                    if source.identity.content_sha256 != dict(binding.content_identities)["actions"] or step.source_sha256 != source.identity.content_sha256:
                        raise ValueError("equity action source differs from pinned input")
                    rows = source.dataframe.loc[source.dataframe.EventId == step.event_id]
                    if len(rows) != 1:
                        raise ValueError("equity action absent from pinned input")
                    row = rows.iloc[0]
                    if (row.Kind, row.Date, row.AvailableDate) != (step.kind, step.effective_at, step.available_at):
                        raise ValueError("equity action dates differ from pinned facts")
                    if step.kind == "SPLIT" and Decimal(str(row.Ratio)) != step.ratio:
                        raise ValueError("equity split ratio differs from pinned facts")
                    if step.kind == "CASH_DIVIDEND" and (Decimal(str(row.CashPerShare)), row.PayAt) != (step.cash_per_share, step.pay_at):
                        raise ValueError("equity dividend payment differs from pinned facts")
                    changed = store.apply_equity_event("equity", **asdict(step))
                    local_coverage.add(step.kind if changed else "DUPLICATE_EVENT")
                    observed.append({"kind": "ACTION", "applied": changed, **step.to_dict()})
                elif type(step) is EquityPteSettle:
                    count = store.settle_equity_receivables("equity", at=step.at)
                    if count:
                        local_coverage.add("SETTLEMENT")
                    observed.append({"kind": "SETTLE", "count": count, "at": step.at.isoformat()})
                if store.account_invariant_violations():
                    raise ValueError("normal account invariants failed")
            facts = _facts(store)
            account = facts["account"]
            if (Decimal(account["cash"]), account["quantity"], Decimal(account["receivable"])) != (
                    scenario.expected_cash, scenario.expected_quantity, scenario.expected_receivable):
                raise ValueError("final equity account differs from declared channel expectation")
            cases.append({"case_id": scenario.case_id, "status": "PASS", "code": "OK", "summary": "Normal equity account path verified",
                          "facts": {**facts, "observed": observed, "coverage": sorted(local_coverage)}})
            coverage.update(local_coverage)
        except Exception as exc:
            cases.append({"case_id": scenario.case_id, "status": "INCOMPLETE" if isinstance(exc, (InterruptedError, TimeoutError)) else "FAIL", "code": type(exc).__name__, "summary": str(exc),
                          "facts": {**_facts(store), "observed": observed, "coverage": sorted(local_coverage)}})
        finally:
            store.close()
    required = {"COMPLETED", "PARTIAL", "DUPLICATE", "RESTART", "REJECTED", "UNKNOWN", "EXPIRED", "RECONCILIATION_BLOCKED"}
    missing = sorted(required - coverage)
    status = "FAIL" if any(c["status"] == "FAIL" for c in cases) else "INCOMPLETE" if missing or any(c["status"] == "INCOMPLETE" for c in cases) else "PASS"
    return {"status": status, "scenarios": cases, "coverage": {"observed": sorted(coverage), "missing": missing},
            "environment": protocol.to_dict()["environment"]}


def verify_equity_inspection_facts(outcome: dict, protocol: dict):
    """Recheck saved ledger arithmetic and declared expectations without running a simulator."""
    declared = EquityPteInspectionProtocol.from_dict(protocol)
    if outcome.get("environment") != protocol["environment"]:
        raise ValueError("equity inspection environment identity differs")
    scenarios = outcome.get("scenarios", [])
    if [x.get("case_id") for x in scenarios] != [s.case_id for s in declared.scenarios]:
        raise ValueError("equity inspection scenario inventory differs")
    all_coverage = set()
    for case, spec in zip(scenarios, declared.scenarios):
        if case.get("status") != "PASS":
            raise ValueError("equity inspection has a nonpassing case")
        facts = case["facts"]
        account = facts["account"]
        if (Decimal(account["cash"]), int(account["quantity"]), Decimal(account["receivable"])) != (
                spec.expected_cash, spec.expected_quantity, spec.expected_receivable):
            raise ValueError("saved equity final expectation differs")
        cash, frozen, quantity = Decimal(facts["initial_cash"]), Decimal(0), 0
        ids = set()
        for row in facts["ledger"]:
            if row["ledger_entry_id"] in ids:
                raise ValueError("duplicate equity ledger entry")
            ids.add(row["ledger_entry_id"])
            cash += Decimal(row["cash_delta"])
            frozen += Decimal(row["frozen_cash_delta"])
            quantity += int(row["quantity_delta"])
            if cash != Decimal(row["balance_after"]) or quantity != int(row["quantity_after"]):
                raise ValueError("saved equity ledger continuity differs")
        if (cash, frozen, quantity) != (Decimal(account["cash"]), Decimal(account["frozen_cash"]), account["quantity"]):
            raise ValueError("saved equity ledger does not reconcile")
        remaining = sum((Decimal(e["amount"]) for e in (json.loads(r["payload"]) for r in facts["events"])
                         if e.get("kind") == "RECEIVABLE" and not e["paid"]), Decimal(0))
        if remaining != Decimal(account["receivable"]):
            raise ValueError("saved equity receivable does not reconcile")
        if len({f["fill_id"] for f in facts["fills"]}) != len(facts["fills"]):
            raise ValueError("duplicate saved channel fill")
        for fill in facts["fills"]:
            entries = [row for row in facts["ledger"] if row["fill_id"] == fill["fill_id"]]
            if len(entries) != 1 or int(entries[0]["quantity_delta"]) != int(fill["quantity"]) * (1 if fill["side"] == "BUY" else -1):
                raise ValueError("saved channel fill differs from account ledger")
        for order in facts["orders"]:
            fills = [f for f in facts["fills"] if f["order_id"] == order["channel_order_id"]]
            quantity = sum(int(f["quantity"]) for f in fills)
            value = sum((Decimal(f["price"])*int(f["quantity"]) for f in fills),Decimal(0))
            if quantity != order["cumulative_filled_quantity"] or quantity > int(order["quantity"]):
                raise ValueError("saved order cumulative quantity differs from fills")
            if quantity and abs(value-Decimal(str(order["average_fill_price"]))*quantity)>Decimal('.0000001'):
                raise ValueError("saved order cumulative value differs from fills")
        observed, coverage, report_keys = facts["observed"], set(), set()
        if len(observed) != len(spec.steps):
            raise ValueError("saved equity step inventory differs")
        for step, actual in zip(spec.steps, observed):
            if type(step) is EquityPteDecision:
                if actual.get("kind") != "DECISION" or actual.get("outcome") != step.expected:
                    raise ValueError("saved equity submission outcome differs")
                coverage.add(step.expected)
            elif type(step) is EquityPteReport:
                order_id = actual.get("channel_order_id")
                if order_id not in {o["channel_order_id"] for o in facts["orders"]} or actual != {"kind":"REPORT", "channel_order_id":order_id, **step.to_dict()}:
                    raise ValueError("saved equity channel report differs")
                key = json.dumps(step.to_dict(), sort_keys=True)
                if key in report_keys:
                    coverage.add("DUPLICATE")
                report_keys.add(key)
                if step.status == "FILLED_PART":
                    coverage.add("PARTIAL")
                if step.status == "FILLED_ALL":
                    coverage.add("COMPLETED")
            elif type(step) is EquityPteRestart:
                if actual.get("kind") != "RESTART" or actual.get("before") != actual.get("after") or not actual.get("before"):
                    raise ValueError("saved restart comparison failed")
                coverage.add("RESTART")
            elif type(step) is EquityPteReconcile and actual.get("status") == "BLOCKED":
                coverage.add("RECONCILIATION_BLOCKED")
            elif type(step) is EquityPteAction:
                coverage.add(step.kind if actual["applied"] else "DUPLICATE_EVENT")
            elif type(step) is EquityPteSettle and actual["count"]:
                coverage.add("SETTLEMENT")
        if sorted(coverage) != facts["coverage"]:
            raise ValueError("saved equity coverage differs from observed steps")
        all_coverage.update(coverage)
    required = {"COMPLETED", "PARTIAL", "DUPLICATE", "RESTART", "REJECTED", "UNKNOWN", "EXPIRED", "RECONCILIATION_BLOCKED"}
    if outcome.get("status") != "PASS" or outcome.get("coverage") != {"observed": sorted(all_coverage), "missing": sorted(required-all_coverage)} or required-all_coverage:
        raise ValueError("equity inspection coverage is incomplete")
    return True
