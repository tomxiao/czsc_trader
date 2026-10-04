"""Command-line entry point for one-shot and continuous paper trading."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from decimal import Decimal
import json
from pathlib import Path
import socket
import sqlite3
import secrets
import sys
from threading import Event, Thread
import time
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import load_dotenv
from dataflows import DataSpace

from .audit import AuditRecorder
from .srt_advice_client import SrtAdviceClient
from .data_space import create_dataflows
from .account_binding import AccountStrategyBinding
from .account_retirement import AccountRetirementRequest
from .account_data_preparer import AccountDataPreparer
from .account_strategy_cycle import AccountStrategyCycle
from .account_engine import AccountEngine
from .account_chart import AccountChartService
from .chart_market_data import AccountChartMarketData
from .futu_execution import FutuExecution
from .futu_gateway import FutuGateway
from .channel import FUTU_SIMULATE_CN_CHANNEL_ID
from .store import PaperStore, backup_runtime_database
from .scheduler import RuntimeScheduler
from .web import create_server
from .coordinator import PteCoordinator, ReconnectableExecution
from .runtime_lock import RuntimeDatabaseLock
from .trading_window import shanghai_now
from .runtime_release import load_manifest_identity


class PortUnavailableError(RuntimeError):
    pass


def probe_port(host: str, port: int) -> None:
    candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        candidate.bind((host, int(port)))
    except OSError as exc:
        raise PortUnavailableError(f"{host}:{port} is already in use") from exc
    finally:
        candidate.close()


class PteParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        result = super().parse_args(args, namespace)
        result.repo_root = result.repo_root.resolve()
        result.config_root = (
            result.config_root.resolve() if result.config_root else result.repo_root
        )
        result.release_manifest = (
            result.release_manifest.resolve() if result.release_manifest else None
        )
        result.runtime_identity = (
            load_manifest_identity(result.release_manifest)
            if result.release_manifest
            else {"mode": "DEV", "repo_root": str(result.repo_root)}
        )
        if result.database is None:
            result.database = result.repo_root / "state" / "paper_trading" / "runtime.db"
        if result.data_dir is None:
            result.data_dir = result.repo_root / "state" / "paper_trading" / "data"
        result.data_space = DataSpace(result.data_space)
        return result


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--symbol", default="588080.SH")
    parser.add_argument("--asset", choices=("etf", "stock"), default="etf")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--data-space", type=Path, default=Path("market"))
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    parser.add_argument("--opend-host", default="127.0.0.1")
    parser.add_argument("--opend-port", default=11111, type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = PteParser(prog="pte")
    actions = parser.add_subparsers(dest="action", required=True)
    once = actions.add_parser("once")
    _common(once)
    serve = actions.add_parser("serve")
    _common(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8080, type=int)
    serve.add_argument("--order-interval", default=5.0, type=float)
    serve.add_argument("--account-interval", default=60.0, type=float)
    serve.add_argument("--data-prepare-interval", default=5.0, type=float)
    serve.add_argument(
        "--data-prepare-time", default="20:30",
    )
    account = actions.add_parser("account")
    account_actions = account.add_subparsers(dest="account_action", required=True)
    for name in ("list", "pause", "resume"):
        leaf = account_actions.add_parser(name)
        _common(leaf)
        if name != "list":
            leaf.add_argument("--account-id", required=True)
    create = account_actions.add_parser("create")
    _common(create)
    create.add_argument("--account-id", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--strategy", required=True)
    create.add_argument("--strategy-version")
    create.add_argument("--initial-cash", default="100000")
    reconciliation = account_actions.add_parser("create-reconciliation")
    _common(reconciliation)
    reconciliation.add_argument("--account-id", default="futu-simulate-cn-reconciliation")
    performance = actions.add_parser("performance")
    performance_actions = performance.add_subparsers(dest="performance_action", required=True)
    export = performance_actions.add_parser("export")
    _common(export)
    export.add_argument("--account-id", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--recorded-by", required=True)
    export.add_argument("--start")
    export.add_argument("--end")
    control = actions.add_parser("control")
    control_actions = control.add_subparsers(dest="control_action", required=True)
    restart = control_actions.add_parser("restart")
    _common(restart)
    restart.add_argument("--host", default="127.0.0.1")
    restart.add_argument("--port", default=8080, type=int)
    restart.add_argument("--wait", default=60.0, type=float)
    repair = control_actions.add_parser("repair-ledger")
    _common(repair)
    repair.add_argument("--host", default="127.0.0.1")
    repair.add_argument("--port", default=8080, type=int)
    repair.add_argument("--account-id", required=True)
    repair.add_argument("--intent-id", required=True)
    reconciliation = control_actions.add_parser("create-reconciliation")
    _common(reconciliation)
    reconciliation.add_argument("--host", default="127.0.0.1")
    reconciliation.add_argument("--port", default=8080, type=int)
    retire = control_actions.add_parser("retire-account")
    _common(retire)
    retire.add_argument("--host", default="127.0.0.1")
    retire.add_argument("--port", default=8080, type=int)
    retire.add_argument("--account-id", required=True)
    retire.add_argument("--expected-release-hash", required=True)
    retire.add_argument("--actor", required=True)
    retire.add_argument("--reason", required=True)
    return parser


def build_engine(args: argparse.Namespace):
    startup_timings: dict[str, float] = {}
    stage_started = time.perf_counter()
    if getattr(args, "action", None) == "serve":
        backup_runtime_database(args.database)
    startup_timings["database_backup_ms"] = round(
        (time.perf_counter() - stage_started) * 1000, 1,
    )
    stage_started = time.perf_counter()
    store = PaperStore(args.database)
    audit = AuditRecorder(store)
    dataflows = create_dataflows(
        data_dir=args.data_dir, space=args.data_space, config_root=args.config_root,
    )
    advice = SrtAdviceClient(
        repo_root=args.repo_root,
        data_dir=args.data_dir,
        asset=args.asset,
        audit=audit,
        dataflows=dataflows,
    )
    startup_timings["store_and_advice_ms"] = round(
        (time.perf_counter() - stage_started) * 1000, 1,
    )
    stage_started = time.perf_counter()
    try:
        deployments = _strategy_deployments(advice, store.strategy_virtual_accounts())
    except Exception:
        store.close()
        raise
    startup_timings["strategy_deployments_ms"] = round(
        (time.perf_counter() - stage_started) * 1000, 1,
    )

    def connect_execution():
        gateway = FutuGateway(host=args.opend_host, port=args.opend_port, audit=audit)
        return FutuExecution(store, gateway, audit=audit)

    stage_started = time.perf_counter()
    try:
        initial_execution = connect_execution()
    except Exception as exc:
        audit.record(
            "DEPENDENCY_DEGRADED", source="cli", outcome="FAILURE",
            actor_type="EXTERNAL", actor_id="futu", channel=FUTU_SIMULATE_CN_CHANNEL_ID,
            details={"service": "futu", "operation": "initialize", "error": str(exc)},
        )
        execution = ReconnectableExecution(
            store, args.symbol, connect_execution, error=exc,
        )
    else:
        execution = ReconnectableExecution(
            store, args.symbol, connect_execution, initial=initial_execution,
        )
    startup_timings["execution_initialize_ms"] = round(
        (time.perf_counter() - stage_started) * 1000, 1,
    )
    stage_started = time.perf_counter()
    _backfill_selection_cutoffs(
        store, audit, deployments,
    )
    _synchronize_strategy_names(
        store, audit, deployments,
    )
    startup_timings["account_metadata_sync_ms"] = round(
        (time.perf_counter() - stage_started) * 1000, 1,
    )
    stage_started = time.perf_counter()
    account_chart = AccountChartService(
        store,
        market_data=AccountChartMarketData(dataflows=dataflows),
        cache_dir=args.database.parent / "charts",
        audit=audit,
    )
    startup_timings["chart_service_ms"] = round(
        (time.perf_counter() - stage_started) * 1000, 1,
    )
    account_engine = AccountEngine(store, advice, audit=audit)
    strategy_cycle = AccountStrategyCycle(
        account_engine,
        AccountDataPreparer(advice=advice),
        store,
        audit=audit,
    )
    return PteCoordinator(
        account_engine,
        execution,
        audit=audit,
        account_chart=account_chart,
        strategy_cycle=strategy_cycle,
        startup_timings=startup_timings,
        runtime_identity=args.runtime_identity,
    )


def _strategy_deployments(
    client: SrtAdviceClient,
    accounts: list[dict[str, object]],
) -> dict[str, AccountStrategyBinding]:
    bindings = {}
    deployments = {}
    for account in accounts:
        if account.get("status") == "RETIRED":
            continue
        key = (
            account["strategy_id"], account["strategy_version"],
            account["symbol"], account["asset_type"],
        )
        if key not in bindings:
            bindings[key] = client.validate_account_binding(
                strategy_id=key[0], strategy_version=key[1], symbol=key[2], asset=key[3],
            )
        binding = bindings[key]
        if binding.release_hash != account["release_hash"]:
            raise RuntimeError(f"{account['account_id']}: account release hash differs from frozen strategy")
        cutoff = account.get("selection_data_cutoff")
        if cutoff and cutoff != binding.selection_data_cutoff.isoformat():
            raise RuntimeError(f"{account['account_id']}: account selection cutoff differs from frozen strategy")
        deployments[str(account["account_id"])] = binding
    return deployments


def _validate_strategy(args: argparse.Namespace) -> AccountStrategyBinding:
    return SrtAdviceClient(repo_root=args.repo_root, data_dir=args.data_dir).validate_account_binding(
        strategy_id=args.strategy, strategy_version=args.strategy_version,
        symbol=args.symbol, asset=args.asset,
    )


def _preflight_strategy_account(
    args: argparse.Namespace,
    identity: AccountStrategyBinding,
) -> None:
    """Prove prepared SRT data and the advice contract before account creation."""
    initial_cash = Decimal(args.initial_cash).quantize(Decimal("0.0001"))
    try:
        client = SrtAdviceClient(
            repo_root=args.repo_root,
            data_dir=args.data_dir,
            dataflows=create_dataflows(
                data_dir=args.data_dir, space=args.data_space, config_root=args.config_root,
            ),
        )
        prepared = client.prepare_account_data(
            account_id=args.account_id,
            strategy_id=str(identity.strategy_id),
            strategy_version=str(identity.version),
            symbol=args.symbol,
            asset=args.asset,
            signal_date=client.latest_completed_signal_date(shanghai_now()),
        )
        if prepared is None:
            raise RuntimeError("account creation requires an SSE trading day")
        trading_date = prepared.tradable_window.start
        decision = client.get_decision(
            0,
            float(initial_cash),
            total_assets=float(initial_cash),
            trading_date=trading_date,
            portfolio_revision=0,
            state_revision=0,
            strategy_id=str(identity.strategy_id),
            strategy_version=str(identity.version),
            account_id=args.account_id,
            symbol=args.symbol,
            asset=args.asset,
            prepared=prepared,
        )
    except Exception as exc:
        raise RuntimeError(
            f"{args.symbol}: valid prepared SRT data is required before account creation: {exc}"
        ) from exc
    expected_strategy = (
        identity.strategy_id, identity.version, identity.release_hash,
    )
    actual_strategy = (
        decision.strategy.get("strategy_id"),
        decision.strategy.get("version"),
        decision.strategy.get("release_hash"),
    )
    if actual_strategy != expected_strategy:
        raise RuntimeError("strategy advice identity differs from frozen release")
    if decision.symbol != args.symbol.upper():
        raise RuntimeError("strategy advice data identity differs from virtual account")
    expected_fee = identity.fee_rate
    if decision.fee_rate != float(expected_fee):
        raise RuntimeError("strategy advice fee rate differs from frozen release")


def _backfill_selection_cutoffs(
    store: PaperStore,
    audit: AuditRecorder,
    deployments: dict[str, AccountStrategyBinding],
) -> None:
    for account in store.strategy_virtual_accounts():
        if account.get("status") == "RETIRED":
            continue
        if account.get("selection_data_cutoff"):
            continue
        try:
            identity = deployments.get(str(account["account_id"]))
            if identity is None:
                raise RuntimeError("strategy deployment identity is unavailable")
            if identity.release_hash != account["release_hash"]:
                raise RuntimeError("stored release hash does not match strategy registry")
            if not store.backfill_account_selection_cutoff(
                account["account_id"],
                account["release_hash"],
                identity.selection_data_cutoff.isoformat(),
            ):
                raise RuntimeError("selection cutoff backfill was not applied")
            store.set_setting(f"selection_cutoff_error:{account['account_id']}", "")
        except Exception as exc:
            fingerprint = str(exc)
            key = f"selection_cutoff_error:{account['account_id']}"
            if store.get_setting(key) == fingerprint:
                continue
            audit.record(
                "ACCOUNT_CHART_GENERATION_FAILED",
                source="cli",
                outcome="FAILURE",
                actor_type="ENGINE",
                account_id=account["account_id"],
                strategy_id=account.get("strategy_id"),
                strategy_version=account.get("strategy_version"),
                release_hash=account.get("release_hash"),
                symbol=account.get("symbol"),
                details={"operation": "selection_cutoff_backfill", "error": fingerprint},
            )
            store.set_setting(key, fingerprint)


def _synchronize_strategy_names(
    store: PaperStore,
    audit: AuditRecorder,
    deployments: dict[str, AccountStrategyBinding],
) -> None:
    for account in store.strategy_virtual_accounts():
        if account.get("status") == "RETIRED":
            continue
        try:
            identity = deployments.get(str(account["account_id"]))
            if identity is None:
                raise RuntimeError("strategy deployment identity is unavailable")
            if identity.release_hash != account["release_hash"]:
                raise RuntimeError("stored release hash does not match strategy registry")
            store.synchronize_account_strategy_name(
                str(account["account_id"]),
                str(account["release_hash"]),
                str(identity.name),
            )
            store.set_setting(f"strategy_name_sync_error:{account['account_id']}", "")
        except Exception as exc:
            fingerprint = str(exc)
            key = f"strategy_name_sync_error:{account['account_id']}"
            if store.get_setting(key) == fingerprint:
                continue
            audit.record(
                "DEPENDENCY_DEGRADED",
                source="cli",
                outcome="FAILURE",
                actor_type="ENGINE",
                actor_id="strategy_manager",
                account_id=account["account_id"],
                strategy_id=account.get("strategy_id"),
                strategy_version=account.get("strategy_version"),
                release_hash=account.get("release_hash"),
                symbol=account.get("symbol"),
                details={"operation": "strategy_name_sync", "error": fingerprint},
            )
            store.set_setting(key, fingerprint)


def _read_json(url: str, *, request: Request | None = None, timeout: float = 3.0):
    with urlopen(request or url, timeout=timeout) as response:  # noqa: S310 - localhost only
        return response.status, json.loads(response.read().decode("utf-8"))


def _ensure_control_token(store: PaperStore) -> str:
    token = store.get_setting("control_token")
    if token:
        return token
    token = secrets.token_urlsafe(32)
    store.set_setting("control_token", token)
    return token


def _record_service_lifecycle(
    audit: AuditRecorder, event_type: str, instance_id: str, **details: object,
) -> None:
    audit.record(
        event_type, source="cli", actor_type="ENGINE",
        actor_id=instance_id, details=details,
    )


def _restart_running_pte(args: argparse.Namespace) -> dict[str, object]:
    if args.host != "127.0.0.1":
        raise ValueError("PTE control host must be 127.0.0.1")
    store = PaperStore(args.database)
    try:
        token = store.get_setting("control_token")
    finally:
        store.close()
    if not token:
        raise RuntimeError("PTE control token is unavailable; perform one bootstrap service restart")
    base = f"http://{args.host}:{args.port}"
    try:
        _, current = _read_json(base + "/api/health")
    except URLError:
        # Allows the first graceful restart from a release that predates /api/health.
        _, current = _read_json(base + "/api/system/status")
    old_instance = current.get("instance_id")
    if not old_instance:
        raise RuntimeError("running PTE does not support graceful restart; perform one bootstrap restart")
    request = Request(
        base + "/api/system/restart", data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-PTE-Control-Token": token},
    )
    status, accepted = _read_json(request.full_url, request=request)
    if status != 202 or accepted.get("instance_id") != old_instance:
        raise RuntimeError("PTE restart request was not accepted")
    deadline = time.monotonic() + max(1.0, args.wait)
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            _, latest = _read_json(base + "/api/health", timeout=1.0)
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            continue
        new_instance = latest.get("instance_id")
        if new_instance and new_instance != old_instance:
            return {
                "status": "READY", "old_instance_id": old_instance,
                "new_instance_id": new_instance,
            }
    raise RuntimeError(f"PTE did not become healthy within {args.wait:g} seconds")


def _repair_running_ledger(args: argparse.Namespace) -> dict[str, object]:
    if args.host != "127.0.0.1":
        raise ValueError("PTE control host must be 127.0.0.1")
    store = PaperStore(args.database)
    try:
        token = store.get_setting("control_token")
    finally:
        store.close()
    if not token:
        raise RuntimeError("PTE control token is unavailable")
    url = (
        f"http://{args.host}:{args.port}/api/virtual-accounts/"
        f"{quote(args.account_id, safe='')}/intents/{quote(args.intent_id, safe='')}/repair-ledger"
    )
    request = Request(
        url, data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-PTE-Control-Token": token},
    )
    _, result = _read_json(url, request=request)
    if result.get("status") not in {"REPAIRED", "ALREADY_REPAIRED"}:
        raise RuntimeError("PTE ledger repair returned an invalid status")
    return result


def _retire_running_account(args: argparse.Namespace) -> dict[str, object]:
    if args.host != "127.0.0.1":
        raise ValueError("PTE control host must be 127.0.0.1")
    retirement = AccountRetirementRequest(
        args.account_id, args.expected_release_hash, args.actor, args.reason,
    )
    connection = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT value FROM settings WHERE key='control_token'").fetchone()
    finally:
        connection.close()
    if row is None or not row[0]:
        raise RuntimeError("PTE control token is unavailable")
    url = f"http://{args.host}:{args.port}/api/virtual-accounts/{quote(retirement.account_id, safe='')}/retire"
    payload = {"expected_release_hash": retirement.expected_release_hash,
               "actor": retirement.actor, "reason": retirement.reason}
    request = Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "X-PTE-Control-Token": row[0],
    })
    _, result = _read_json(url, request=request)
    if result.get("status") != "RETIRED" or result.get("account_id") != retirement.account_id:
        raise RuntimeError("PTE account retirement did not complete")
    return result


def _create_running_reconciliation_account(args: argparse.Namespace) -> dict[str, object]:
    if args.host != "127.0.0.1":
        raise ValueError("PTE control host must be 127.0.0.1")
    store = PaperStore(args.database)
    try:
        token = store.get_setting("control_token")
    finally:
        store.close()
    if not token:
        raise RuntimeError("PTE control token is unavailable")
    url = f"http://{args.host}:{args.port}/api/channels/futu-simulate-cn/reconciliation-account"
    request = Request(
        url, data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-PTE-Control-Token": token},
    )
    _, result = _read_json(url, request=request)
    if result.get("account_type") != "CHANNEL_RECONCILIATION":
        raise RuntimeError("PTE did not create the channel reconciliation account")
    return result


def _run_account_command(args: argparse.Namespace) -> dict[str, object] | list[dict[str, object]]:
    store = PaperStore(args.database)
    try:
        if args.account_action == "list":
            return store.strategy_virtual_accounts()
        if args.account_action == "pause":
            return store.set_virtual_paused(args.account_id, True)
        if args.account_action == "resume":
            return store.set_virtual_paused(args.account_id, False)
        if args.account_action == "create-reconciliation":
            return store.create_channel_reconciliation_account(account_id=args.account_id)
        identity = _validate_strategy(args)
        baseline_version = identity.release_id
        baseline_hash = identity.release_hash
        existing = None
        try:
            existing = store.virtual_account(args.account_id)
        except KeyError:
            pass
        if existing is not None:
            if (
                existing["strategy_id"], existing["strategy_version"],
                existing["release_hash"], existing["name"],
                existing["symbol"], existing["asset_type"], existing["initial_cash"],
                existing["selection_data_cutoff"],
            ) != (
                identity.strategy_id, identity.version,
                identity.release_hash,
                args.name, args.symbol.upper(), args.asset,
                str(Decimal(args.initial_cash).quantize(Decimal("0.0001"))),
                identity.selection_data_cutoff.isoformat(),
            ):
                raise ValueError("account id already exists with a different immutable identity")
            return existing
        _preflight_strategy_account(args, identity)
        created = store.create_virtual_account(
            args.account_id, args.name, baseline_version, baseline_hash, args.initial_cash,
            strategy_id=identity.strategy_id,
            strategy_name_snapshot=identity.name,
            strategy_version=identity.version,
            release_hash=identity.release_hash,
            qualification_snapshot=identity.qualification.value,
            selection_data_cutoff=identity.selection_data_cutoff.isoformat(),
            symbol=args.symbol,
            asset_type=args.asset,
        )
        return created
    finally:
        store.close()


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    engine_factory: Callable[[argparse.Namespace], object] = build_engine,
) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.config_root / ".env", override=False)
    engine = None
    runtime_lock = None
    close_engine = True
    try:
        if args.action == "performance":
            from .performance_export import export_performance

            store = PaperStore(args.database)
            try:
                result = export_performance(
                    store,
                    args.account_id,
                    args.output,
                    recorded_by=args.recorded_by,
                    start=args.start,
                    end=args.end,
                )
            finally:
                store.close()
            _write({"status": "PASS", "command": "pte.performance.export", "result": result})
            return 0
        if args.action == "account":
            result = _run_account_command(args)
            _write({"status": "PASS", "command": f"pte.account.{args.account_action}", "result": result})
            return 0
        if args.action == "control":
            if args.control_action == "restart":
                result = _restart_running_pte(args)
            elif args.control_action == "create-reconciliation":
                result = _create_running_reconciliation_account(args)
            elif args.control_action == "retire-account":
                result = _retire_running_account(args)
            else:
                result = _repair_running_ledger(args)
            _write({
                "status": "PASS", "command": f"pte.control.{args.control_action}",
                "result": result,
            })
            return 0
        if args.action == "serve":
            probe_port(args.host, args.port)
        if args.action in {"serve", "once"}:
            runtime_lock = RuntimeDatabaseLock(args.database).acquire()
        engine_build_started = time.perf_counter()
        engine = engine_factory(args)
        engine_build_ms = round((time.perf_counter() - engine_build_started) * 1000, 1)
        if args.action == "once":
            result = engine.refresh()
            _write({"status": "PASS", "command": "pte.once", "result": result})
            return 0
        stopped = Event()
        control_token = _ensure_control_token(engine.store)
        audit = AuditRecorder(engine.store)
        instance_id = uuid4().hex
        server_holder = {}

        def graceful_restart():
            engine.begin_shutdown()
            stopped.set()
            server_holder["server"].shutdown()

        service_startup_started = time.perf_counter()
        stage_started = time.perf_counter()
        engine.startup()
        engine_startup_ms = round((time.perf_counter() - stage_started) * 1000, 1)
        stage_started = time.perf_counter()
        server = create_server(
            engine, host=args.host, port=args.port, control_token=control_token,
            restart_callback=graceful_restart, instance_id=instance_id,
        )
        web_server_ms = round((time.perf_counter() - stage_started) * 1000, 1)
        server_holder["server"] = server
        initial_observation_at = shanghai_now()
        scheduler = RuntimeScheduler(
            engine,
            engine.strategy_cycle,
            engine.store,
            order_interval=args.order_interval,
            account_interval=args.account_interval,
            data_prepare_interval=args.data_prepare_interval,
            preparation_time=args.data_prepare_time,
            audit=audit,
            initial_observation_at=initial_observation_at,
        )
        worker = Thread(target=scheduler.run, args=(stopped,), name="pte-scheduler", daemon=True)
        worker.start()
        _record_service_lifecycle(
            audit, "SERVICE_STARTED", instance_id,
            host=args.host, port=server.server_port,
            startup_duration_ms=round(
                engine_build_ms + (time.perf_counter() - service_startup_started) * 1000,
                1,
            ),
            startup_stages_ms={
                **getattr(engine, "startup_timings", {}),
                "engine_build_total_ms": engine_build_ms,
                "engine_startup_ms": engine_startup_ms,
                "web_server_ms": web_server_ms,
            },
            runtime_release=args.runtime_identity,
        )
        sys.stderr.write(f"PTE listening on http://{args.host}:{server.server_port}\n")
        try:
            server.serve_forever()
        finally:
            stopped.set()
            worker.join(timeout=30.0)
            server.server_close()
            close_engine = not worker.is_alive() and scheduler.shutdown_clean
            if close_engine:
                _record_service_lifecycle(audit, "SERVICE_STOPPED", instance_id)
            else:
                sys.stderr.write(
                    "PTE daily operation did not quiesce before shutdown; "
                    "database close is delegated to process exit.\n"
                )
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _write(
            {
                "status": "FAIL",
                "command": f"pte.{args.action}",
                "error": {"code": "runtime_error", "message": str(exc)},
            }
        )
        return 5
    finally:
        try:
            if engine is not None and close_engine:
                engine.close()
        finally:
            if runtime_lock is not None and close_engine:
                runtime_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
