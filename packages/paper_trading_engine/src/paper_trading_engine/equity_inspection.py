"""Recorded channel scenarios exercising normal durable CN/US account components."""
from .ec_boundary import execution_rules, execution_permit

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from functools import cached_property

from dataflows import Dataflows, EquityDataRequest, TimeInterval
from strategy_runtime import EquityInputBinding
from strategy_runtime.inspection import InspectionEnvironment
from .inspection_contracts import Record, _case_id, _money, _time
from execution_channels.futu.equity_contracts import EquityOrderReport, EquityReconciliationError
from execution_channels.futu.broker import BrokerSubmissionUncertainError
from .account_engine import AccountEngine, AccountDecisionBlockedError
from .account_chart import AccountChartService, OUTPUT_LIMIT
from .forward_chart import render_forward_chart_html
from execution_channels.futu.store import PaperStore
from execution_channels.futu.channel import ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID
from execution_channels.futu.futu_execution import ChannelExecution, ChannelReconciliationError
from .equity_runtime import EquityRuntimeAdviceClient
from .inspection_broker import RecordedInspectionBroker


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
class EquityPteSettle(Record):
    at: datetime

    def __post_init__(self):
        _time(self.at)


EquityPteStep = EquityPteDecision | EquityPteReport | EquityPteRestart | EquityPteReconcile | EquityPteSettle


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
                EquityPteDecision, EquityPteReport, EquityPteRestart, EquityPteReconcile, EquityPteSettle) for s in self.steps):
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


def _facts(store):
    account = store.virtual_account("equity")
    return {"initial_cash": account["initial_cash"], "v4_state": account.get("account_v4_json"), "account": {k: account[k] for k in ("cash", "frozen_cash", "quantity", "average_cost", "receivable", "realized_pnl", "total_assets", "health")},
            "decisions": store.account_decisions("equity"), "orders": store.account_orders("equity"),
            "intents": store.account_intents("equity"),
            "fills": [dict(r) for r in store._connection.execute("SELECT * FROM fills WHERE account_id='equity' ORDER BY rowid")],
            "ledger": [dict(r) for r in store._connection.execute("SELECT * FROM account_ledger WHERE account_id='equity' ORDER BY rowid")],
            "events": [dict(r) for r in store._connection.execute("SELECT * FROM equity_account_events WHERE account_id='equity' ORDER BY event_id")]}


@dataclass
class _InspectionChartMarketData:
    dataflows: Dataflows
    binding: EquityInputBinding
    request: EquityDataRequest

    @cached_property
    def daily(self):
        result = self.dataflows.fetch(self.request, prepared=self.binding.prepared)
        if not result.ready or result.identity.content_sha256 != self.binding.expected_identities["bars"]:
            raise ValueError("forward chart HFQ input differs from the inspected product")
        frame = result.dataframe.sort_values("Date").dropna(subset=["Open", "High", "Low", "Close"])
        sessions = frame["Date"].dt.tz_convert(self.binding.instrument.timezone).dt.date
        daily = frame.groupby(sessions).agg(Open=("Open", "first"), High=("High", "max"),
                                            Low=("Low", "min"), Close=("Close", "last"))
        return result.identity.content_sha256, daily.rename_axis("Date").reset_index()

    def history(self, **_):
        return self.daily


def _inspect_forward_chart(store, facts, market_data, cache_dir, *, strategy_root=None):
    rows = facts["decisions"]
    # Use the same projection and renderer as the account console, with the
    # isolated HFQ product and saved account facts.
    chart = AccountChartService(store, market_data=market_data, cache_dir=cache_dir, strategy_root=strategy_root)
    try:
        context = chart._request(store.virtual_account("equity"))
    finally:
        chart.close()
    events = context["execution"]["decisions"]
    if len(events) != len(rows):
        raise ValueError("forward chart omitted saved decisions")
    for row, event in zip(rows, events, strict=True):
        for field in ("decision_id", "signal_date", "valid_session", "generated_at", "status", "state_reason"):
            if row[field] != event[field]:
                raise ValueError(f"forward chart decision {field} differs from the stored fact")
        payload = row["payload"]
        for field in ("action", "target_quantity"):
            if payload.get(field) != event[field]:
                raise ValueError(f"forward chart decision {field} differs from the stored fact")
        explanation = (payload.get("strategy_output") or {}).get("explanation")
        if explanation is None or event["explanation"] != explanation:
            raise ValueError("forward chart is missing the saved strategy explanation")
    html = render_forward_chart_html(context, inline_assets=True)
    if len(html.encode("utf-8")) > OUTPUT_LIMIT:
        raise ValueError("isolated forward chart exceeds the publication size limit")
    return {"status": "PASS", "first_signal_date": context["window"]["forward_observation_start"],
            "decision_count": len(rows), "html": html}


def inspect_equity_release(*, candidate, dataflows, binding, requests, execution_reference, initial_cash, fee_rate, permit, protocol,
                           control=None, step_data_windows=()):
    """Consume explicit channel facts; never infer fills from a historical price bar."""
    if type(protocol) is not EquityPteInspectionProtocol:
        raise TypeError("equity inspection requires explicit channel protocol")
    from strategy_runtime import STEP_DATA_CONTRACT
    if candidate.definition.contract_version != STEP_DATA_CONTRACT:
        raise ValueError('account inspection requires the V5 DFLS step contract')
    market_data = _InspectionChartMarketData(dataflows, binding, dict(binding.bind_requests(requests))["bars"])
    candidate.verify()
    from strategy_runtime.deployment import validate_release_package
    verified = validate_release_package(permit.isolated_repository / "strategies", permit.release_id)
    permit.validate_release(verified.release.release_id, verified.release.release_hash)
    from strategy_runtime import EquityStrategyDefinition
    if (verified.package_sha256 != permit.package_sha256 or candidate.source_root.resolve() != verified.source_root.resolve()
            or candidate.strategy_id != verified.release.strategy_family_id or candidate.candidate_id != verified.runtime_candidate_id
            or candidate.definition != EquityStrategyDefinition.from_dict(dict(verified.release.payload["equity_definition"]))):
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
    cases, charts, coverage = [], {}, set()
    runtime = {}
    channel_id = FUTU_SIMULATE_CN_CHANNEL_ID if candidate.instrument.market.value == 'CN' else FUTU_US_SIM_CHANNEL_ID
    config = ChannelAccountConfig('inspection-channel', channel_id, 1)
    for scenario in protocol.scenarios:
        checkpoint()
        path = permit.validate_path(permit.workspace / "equity-pte" / scenario.case_id / "paper.db")
        if path.exists():
            raise ValueError("equity scenario database already exists")
        store = PaperStore(path, inspection_permit=execution_permit(permit))
        observed = []
        local_coverage = set()
        try:
            store = store.register_channel_account(config, capital=Decimal(str(initial_cash)))
            store.set_paused(False)
            release_record = json.loads((permit.isolated_repository / "strategies" / candidate.strategy_id /
                "versions" / (verified.release.version + ".json")).read_text(encoding="utf-8"))
            store.create_virtual_account("equity", "Isolated equity inspection", "inspection", permit.release_sha256,
                initial_cash, symbol=candidate.instrument.symbol, asset_type=candidate.instrument.asset_class.value.lower(), strategy_id=candidate.strategy_id,
                strategy_name_snapshot="Isolated equity inspection", strategy_version=permit.release_id.split("-")[1],
                release_hash=permit.release_sha256, qualification_snapshot="INSPECTION", selection_data_cutoff=release_record["selection_data_cutoff"],
                channel_id=channel_id, equity_rules=execution_rules(candidate.instrument, candidate.definition.execution_spec))
            store.set_virtual_paused("equity", False)
            now = next((s.interval.start for s in scenario.steps if type(s) is EquityPteDecision), None)
            channel = RecordedInspectionBroker(config, cash=initial_cash, symbol=candidate.instrument.symbol,
                       fee_rate=fee_rate, now=lambda: now)
            channel.channel_id = channel_id
            orders, reports = [], set()
            def advice_client():
                client = EquityRuntimeAdviceClient(repo_root=permit.isolated_repository, store=store,
                    dataflows=dataflows, data_dir=path.parent, inspection_permit=permit,
                    inspection_data_windows=step_data_windows)
                client.register_inputs('equity', binding, expected_release_hash=permit.release_sha256,
                    fee_rate=fee_rate, execution_reference=execution_reference)
                return client
            advice = advice_client()
            for step in scenario.steps:
                checkpoint()
                if type(step) is EquityPteRestart:
                    before = _facts(store)
                    store.close()
                    store = PaperStore(path, inspection_permit=execution_permit(permit))
                    store = store.scope(config.channel_account_id)
                    advice = advice_client()
                    if _facts(store) != before:
                        raise ValueError("reopened equity account differs from durable state")
                    local_coverage.add("RESTART")
                    observed.append({"kind": "RESTART", "before": before, "after": _facts(store)})
                    continue
                execution = ChannelExecution(store, channel, now=lambda: now, config=config)
                runtime = {'advice': type(advice).__name__, 'execution': type(execution).__name__,
                           'account_engine': AccountEngine.__name__, 'store': type(store).__name__,
                           'admission': store.virtual_account('equity')['qualification_snapshot']}
                if type(step) is EquityPteReconcile:
                    try:
                        channel.cash, channel.quantity = step.cash, step.quantity
                        execution.refresh_orders()
                        observed.append({"kind": "RECONCILE", "status": "OK"})
                    except ChannelReconciliationError:
                        local_coverage.add("RECONCILIATION_BLOCKED")
                        observed.append({"kind": "RECONCILE", "status": "BLOCKED"})
                elif type(step) is EquityPteDecision:
                    now, channel.outcome = step.at, step.outcome
                    expired_intents = []
                    prepared = advice.prepare_interval('equity', step.interval, observed_at=step.interval.start)
                    try:
                        AccountEngine(store, advice, now=lambda: now).refresh_account("equity", prepared=prepared)
                        before_submission = {row['intent_id']: row['status'] for row in store.account_intents('equity')}
                        execution.submit_pending()
                        ids = [o['channel_order_id'] for o in store.account_orders('equity')
                               if o['channel_order_id'] not in orders]
                        orders.extend(ids)
                        actual = "SUBMITTED" if ids else "NO_ORDER"
                        for row in store.account_intents('equity'):
                            bounds = execution._execution_interval(row)
                            if (before_submission.get(row['intent_id']) == 'PENDING_SUBMIT'
                                    and row['status'] == 'EXPIRED' and bounds is not None and now >= bounds[1]):
                                expired_intents.append(row['intent_id'])
                        changed = {r['status'] for r in store.account_intents('equity')
                                   if r['status'] != before_submission.get(r['intent_id'])}
                        if 'REJECTED' in changed:
                            actual = 'REJECTED'
                        elif expired_intents and now >= step.interval.end:
                            actual = 'EXPIRED'
                    except BrokerSubmissionUncertainError:
                        actual = "UNKNOWN"
                    except (AccountDecisionBlockedError, EquityReconciliationError):
                        if store.get_setting('channel_reconciliation_status') != 'BLOCKED':
                            raise
                        actual = 'RECONCILIATION_BLOCKED'
                    except ChannelReconciliationError:
                        actual = "RECONCILIATION_BLOCKED"
                    if actual != step.expected:
                        raise ValueError(f"expected {step.expected}, observed {actual}")
                    local_coverage.add(actual)
                    extra = {}
                    health = store.virtual_account('equity')['health']
                    reconciliation = store.get_setting('channel_reconciliation_status')
                    if actual == 'UNKNOWN' and health != 'BLOCKED':
                        raise ValueError('unknown channel submission must block the account')
                    if actual in ('REJECTED', 'EXPIRED', 'NO_ORDER', 'SUBMITTED') and health != 'OK':
                        raise ValueError('ordinary execution outcome must preserve a healthy account')
                    if actual == 'RECONCILIATION_BLOCKED' and reconciliation != 'BLOCKED':
                        raise ValueError('unreconciled channel facts must block channel execution')
                    extra = {'account_health': health, 'channel_reconciliation': reconciliation}
                    if expired_intents:
                        local_coverage.add('EXPIRED')
                        extra = {**extra, 'expired_intents': expired_intents,
                                 'submission_intents_before': before_submission}
                    observed.append({"kind": "DECISION", "outcome": actual, "interval": step.interval.to_dict() if hasattr(step.interval, "to_dict") else {"start":step.interval.start.isoformat(),"end":step.interval.end.isoformat()}, **extra})
                elif type(step) is EquityPteReport:
                    report = EquityOrderReport(orders[step.order_index], step.cumulative_quantity, step.average_price, step.at, step.status, step.settlement_at)
                    before = _facts(store)
                    now = step.at
                    channel.apply_recorded_report(execution.broker.raw_id(report.channel_order_id), report)
                    execution.refresh_orders()
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
            if facts["decisions"]:
                try:
                    charts[scenario.case_id] = _inspect_forward_chart(store, facts, market_data, path.parent,
                        strategy_root=permit.isolated_repository / 'strategies')
                except Exception as exc:
                    charts[scenario.case_id] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:
            cases.append({"case_id": scenario.case_id, "status": "INCOMPLETE" if isinstance(exc, (InterruptedError, TimeoutError)) else "FAIL", "code": type(exc).__name__, "summary": str(exc),
                          "facts": {**_facts(store), "observed": observed, "coverage": sorted(local_coverage)}})
        finally:
            store.close()
    required = {"COMPLETED", "PARTIAL", "DUPLICATE", "RESTART", "REJECTED", "UNKNOWN", "EXPIRED", "RECONCILIATION_BLOCKED"}
    missing = sorted(required - coverage)
    status = "FAIL" if any(c["status"] == "FAIL" for c in cases) else "INCOMPLETE" if missing or any(c["status"] == "INCOMPLETE" for c in cases) else "PASS"
    chart_status = ("FAIL" if any(c["status"] == "FAIL" for c in charts.values())
                    else "PASS" if charts else "INCOMPLETE")
    return {"status": status, "scenarios": cases, "coverage": {"observed": sorted(coverage), "missing": missing},
            "forward_chart": {"status": chart_status, "scenarios": charts},
            "runtime": runtime,
            "environment": protocol.to_dict()["environment"]}


def verify_equity_inspection_facts(outcome: dict, protocol: dict, *, historical=False):
    """Recheck saved ledger arithmetic and declared expectations without running a simulator."""
    declared = EquityPteInspectionProtocol.from_dict(protocol)
    advice = 'FormalV4AdviceClient' if historical else EquityRuntimeAdviceClient.__name__
    if outcome.get('runtime') != {'advice': advice, 'execution': 'ChannelExecution',
            'account_engine': 'AccountEngine', 'store': 'PaperStore', 'admission': 'INSPECTION'}:
        raise ValueError('saved inspection runtime identity differs from its protocol')
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
        expired_seen = set()
        if len(observed) != len(spec.steps):
            raise ValueError("saved equity step inventory differs")
        for step, actual in zip(spec.steps, observed):
            if type(step) is EquityPteDecision:
                if actual.get("kind") != "DECISION" or actual.get("outcome") != step.expected:
                    raise ValueError("saved equity submission outcome differs")
                coverage.add(step.expected)
                expected_health = 'BLOCKED' if step.expected == 'UNKNOWN' else 'OK'
                if step.expected == 'RECONCILIATION_BLOCKED':
                    if actual.get('channel_reconciliation') != 'BLOCKED':
                        raise ValueError('saved unreconciled channel is not blocked')
                elif actual.get('account_health') != expected_health:
                    raise ValueError('saved execution health differs from the formal outcome')
                if 'expired_intents' in actual or 'submission_intents_before' in actual:
                    from execution_channels.futu.order_windows import planned_bounds
                    expired = actual.get('expired_intents')
                    before = actual.get('submission_intents_before')
                    if (step.expected not in ('NO_ORDER', 'SUBMITTED', 'EXPIRED') or type(expired) is not list
                            or not expired or len(set(expired)) != len(expired) or type(before) is not dict):
                        raise ValueError('saved expiry transition is invalid')
                    intents = {row['intent_id']: row for row in facts['intents']}
                    decisions = {row['decision_id']: row for row in facts['decisions']}
                    for intent_id in expired:
                        row = intents.get(intent_id)
                        interval = None if row is None else decisions.get(row['decision_id'], {}).get('payload', {}).get('equity_execution_interval')
                        bounds = None if interval is None else tuple(datetime.fromisoformat(interval[key]) for key in ('start', 'end'))
                        if row is not None:
                            planned = planned_bounds(row['payload'], row['valid_session'],
                                **({'zone': bounds[0].tzinfo} if bounds else {}))
                            if planned is not None:
                                bounds = planned if bounds is None else (max(bounds[0], planned[0]), min(bounds[1], planned[1]))
                        if (intent_id in expired_seen or before.get(intent_id) != 'PENDING_SUBMIT'
                                or row is None or row['status'] != 'EXPIRED' or bounds is None or step.at < bounds[1]):
                            raise ValueError('saved expiry is not a new submit-time transition')
                        expired_seen.add(intent_id)
                    coverage.add('EXPIRED')
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
            elif type(step) is EquityPteSettle and actual["count"]:
                coverage.add("SETTLEMENT")
        if sorted(coverage) != facts["coverage"]:
            raise ValueError("saved equity coverage differs from observed steps")
        all_coverage.update(coverage)
    required = {"COMPLETED", "PARTIAL", "DUPLICATE", "RESTART", "REJECTED", "UNKNOWN", "EXPIRED", "RECONCILIATION_BLOCKED"}
    if outcome.get("status") != "PASS" or outcome.get("coverage") != {"observed": sorted(all_coverage), "missing": sorted(required-all_coverage)} or required-all_coverage:
        raise ValueError("equity inspection coverage is incomplete")
    return True
