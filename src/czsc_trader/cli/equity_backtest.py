"""Replay a verified frozen V5 account against an explicit DFLS preparation."""

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from math import isfinite
from pathlib import Path
from uuid import UUID

from dataflows import (BarFrequency, Dataflows, DataSpace, EquityDataRequest, EquityProduct, EquityQuery,
                       MarketId, PreparedDataRef, PreparePolicy, PriceAdjustment, ProviderConfig, SourceRef, TimeInterval)
from dataflows.asset_store import StoreError
from dataflows.equity_data import sessions_from_metadata
from dataflows.tushare_equity import tushare_historical_equity_bindings
from strategy_manager import StrategyRegistry, StrategyVersion
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, ExecutionPriceBasis, StepDataWindow
from strategy_runtime.data_preparation import prepare_observations
from strategy_runtime.deployment import validate_release_package
from strategy_runtime.errors import StrategyRuntimeError

from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.errors import ExecutionError, ValidationError
from czsc_trader.backtesting.equity_report import equity_report
from czsc_trader.backtesting.service import _backtest_report_files
from czsc_trader.backtesting.strategy_source import registered_snapshot
from czsc_trader.research_tools.equity_evaluation import (
    EquityArtifact, EquitySources, equity_product_requests, fetch_equity_products, _records,
)
from czsc_trader.research_tools.equity_replay import (
    _AccountOutputContext, _ReplayAccountRequest, _bytes, _compute_account, _read,
)

CN_SOURCE = SourceRef("tushare-cn-market", "v1")


@dataclass(frozen=True, slots=True)
class EquityBacktestRequest:
    symbol: str
    asset_type: str
    start: date
    end: date
    initial_cash: float
    lot_size: int
    price_basis: ExecutionPriceBasis
    space: DataSpace
    prepared: PreparedDataRef | None
    history_start: date
    fee_rate: float | None
    sources: EquitySources
    step_data_windows: tuple[StepDataWindow, ...]

    def __post_init__(self):
        if not self.history_start <= self.start <= self.end:
            raise ValueError("V5 history_start, start and end must be ordered")
        if not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        if self.fee_rate is not None and (type(self.fee_rate) not in (int, float)
                or not isfinite(self.fee_rate) or not 0 <= self.fee_rate < 1):
            raise ValueError("fee_rate must be finite and in [0, 1)")
        if self.price_basis is not ExecutionPriceBasis.HFQ_RESEARCH:
            raise ValueError("V5 historical accounts require HFQ_RESEARCH")
        names = [window.name for window in self.step_data_windows]
        if len(names) != len(set(names)) or any(window.end > self.end for window in self.step_data_windows):
            raise ValueError("V5 step windows must have distinct names and end within the backtest")

    @classmethod
    def from_cli(cls, path: Path | None, *, data_space: Path | None, fee_rate: float | None, symbol: str,
                  asset_type: str, start: date, end: date, initial_cash: float, lot_size: int,
                  price_basis: ExecutionPriceBasis) -> "EquityBacktestRequest":
        try:
            if (path is None) != (data_space is None):
                raise ValueError("--input-binding and --data-space must be supplied together")
            if path is None:
                return cls(symbol, asset_type, start, end, initial_cash, lot_size, price_basis,
                           DataSpace(Path("data/backtest")), None, start, fee_rate,
                           EquitySources(CN_SOURCE, CN_SOURCE, CN_SOURCE), ())
            value = _read(path.read_bytes())
            fields = {"prepared", "history_start", "sources", "step_data_windows"}
            if type(value) is not dict or not fields <= value.keys() or value.keys() - fields - {"data_space", "fee_rate"}:
                raise ValueError("V5 equity inputs require: " + ", ".join(sorted(fields)))
            if "data_space" in value and Path(value["data_space"]) != data_space:
                raise ValueError("--data-space differs from the prepared input binding")
            prep = value["prepared"]
            if type(prep) is not dict or set(prep) != {"space_id", "preparation_id", "manifest_sha256"}:
                raise ValueError("prepared must identify one DFLS space, preparation and manifest hash")
            reference = PreparedDataRef(UUID(prep["space_id"]), UUID(prep["preparation_id"]), prep["manifest_sha256"])
            if type(value["sources"]) is not dict:
                raise ValueError("sources must declare bars, sessions and trading_facts")
            sources = EquitySources(**{role: SourceRef(**source) for role, source in value["sources"].items()})
            windows = value["step_data_windows"]
            if type(windows) is not list or any(type(window) is not dict or set(window) != {"name", "start", "end"}
                                                for window in windows):
                raise ValueError("step_data_windows must be a list of name, start and end objects")
            return cls(symbol, asset_type, start, end, initial_cash, lot_size, price_basis,
                       DataSpace(data_space), reference, date.fromisoformat(value["history_start"]),
                       value.get("fee_rate") if fee_rate is None else fee_rate,
                       sources, tuple(StepDataWindow.from_dict(window) for window in windows))
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            raise ValidationError("backtest_request_invalid", str(exc)) from exc


def run_equity_backtest(repository: RepositoryContext, strategy: StrategyVersion,
                        request: EquityBacktestRequest) -> tuple[dict[str, bytes], dict[str, object]]:
    reference = strategy.release_id
    try:
        package = validate_release_package(repository.strategy_root, reference)
        if package.release.release_hash != strategy.release_hash:
            raise ValueError("frozen release changed after CLI strategy selection")
        definition = EquityStrategyDefinition.from_dict(dict(package.release.payload["equity_definition"]))
    except (OSError, ValueError, StrategyRuntimeError) as exc:
        raise ValidationError("backtest_strategy_invalid", str(exc), context={"strategy": reference}) from exc

    instrument, spec = definition.instrument, definition.execution_spec
    symbols = {instrument.symbol}
    if instrument.market is MarketId.US:
        symbols.add(instrument.symbol + ".US")
    if request.symbol.upper() not in symbols or request.asset_type != instrument.asset_class.value.lower():
        raise ValidationError("backtest_request_invalid", "symbol and asset must match the frozen V5 instrument")
    if request.lot_size != spec.quantity_step:
        raise ValidationError("backtest_request_invalid", "lot_size must match the frozen V5 quantity step")
    if {window.name for window in request.step_data_windows} - {item.name for item in definition.step_data_inputs}:
        raise ValidationError("backtest_request_invalid", "step windows must reference declared V5 inputs")
    if request.prepared is None and (instrument.market is not MarketId.CN or any(
            item.source not in (None, CN_SOURCE) for item in definition.step_data_inputs)
            or (definition.execution_input is not None and definition.execution_input.source != CN_SOURCE)):
        raise ValidationError("backtest_request_invalid", "this frozen source requires --input-binding and --data-space")
    if request.fee_rate is None:
        settings = definition.execution_policy.settings
        fee = settings.get("capital", {}).get("fee_rate", settings.get("one_way_cost"))
        if fee is None:
            raise ValidationError("backtest_request_invalid", "--fee-rate is required when the frozen policy has no model fee")
        request = replace(request, fee_rate=fee)

    candidate = EquityStrategyCandidate(strategy.strategy_id, package.runtime_candidate_id, definition, package.source_root)
    try:
        policy = ProviderConfig(bindings={})
        if request.prepared is None:
            env_file = repository.root / ".env"
            policy = ProviderConfig(env_file=env_file,
                equity_bindings=tushare_historical_equity_bindings(source=CN_SOURCE, env_file=env_file))
            request = replace(request,
                history_start=request.start - timedelta(days=max(90, definition.warmup_bars * 3)),
                step_data_windows=tuple(StepDataWindow(item.name,
                    request.start - timedelta(days=item.max_calendar_days), request.end)
                    for item in definition.step_data_inputs))
        else:
            space_root = (repository.root / request.space.path).resolve()
            if not space_root.is_relative_to(repository.root) or not (space_root / "assets.sqlite3").is_file():
                raise ValueError("data_space must locate an existing DFLS space inside the repository")
        flows = Dataflows(base_dir=repository.root, space=request.space, providers=policy)
        items = equity_product_requests(definition, request.sources, request.history_start, request.start, request.end,
                                        specification=spec)
        if spec.decision_clock is not BarFrequency.DAILY:
            items += (("benchmark:bars", EquityDataRequest(instrument, request.sources.bars,
                EquityQuery(EquityProduct.BARS, request.history_start, request.end, BarFrequency.DAILY,
                            PriceAdjustment.BACKWARD))),)
        if request.prepared is None:
            requests = [query for _, query in items] + [item.request(grant, source_root=package.source_root)
                for item, grant in zip(definition.step_data_inputs, request.step_data_windows, strict=True)]
            result = flows.prepare(tuple(dict.fromkeys(requests)), policy=PreparePolicy.REUSE)
            if not result.ready:
                raise ValueError("V5 input preparation failed: " + "; ".join(str(item.error) for item in result.items if not item.ready))
            request = replace(request, prepared=result.reference)
        products, identities = fetch_equity_products(flows, definition, items, request.prepared)
        sessions = [session for session in sessions_from_metadata(identities["sessions"]["metadata"])
                    if request.start <= session.session_date <= request.end]
        if not sessions:
            raise ValueError("backtest window contains no prepared trading sessions")
        window = TimeInterval(sessions[0].segments[0].start, sessions[-1].segments[-1].end)
        replay = prepare_observations(definition, products, identities)
        inputs = EquityArtifact("equity_input", _bytes({"schema": "equity-input/v2", "data": identities,
            "products": {key: _records(frame) for key, frame in products.items()}}))
        owner = {"kind": "RELEASE", "release_id": reference, "release_hash": strategy.release_hash}
        quotes = products.get("execution:bars")
        account_request = _ReplayAccountRequest(window, request.initial_cash, request.fee_rate, space=flows.binding,
            step_data_reference=request.prepared, step_data_windows=request.step_data_windows)
        output = _AccountOutputContext(inputs.sha256, _bytes(owner), tuple(_records(products["bars"])),
            None if quotes is None else tuple(_records(quotes)), tuple(products["constraints"].to_dict("records")))
        account, _ = _compute_account(replay, candidate, account_request, reference, quotes, output)
        snapshot = registered_snapshot(repository, StrategyRegistry(repository.strategy_root), strategy, package.source_root)
        report = equity_report(snapshot, request, candidate, _read(account.content)["run"], products, identities,
                               request.prepared)
    except (OSError, RuntimeError, StoreError, StrategyRuntimeError, ValueError) as exc:
        raise ExecutionError("backtest_failed", str(exc), context={"strategy": reference}) from exc

    report.manifest.update({"release_hash": strategy.release_hash, "package_sha256": package.package_sha256,
        "execution_window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "sources": asdict(request.sources), "data_space": request.space.path.as_posix(),
        "prepared": {key: str(value) for key, value in asdict(request.prepared).items()},
        "step_data_windows": [item.to_dict() for item in request.step_data_windows],
        "artifacts": {"inputs.json": inputs.reference(), "account.json": account.reference()}})
    files = _backtest_report_files(report, content_addressed_links=False)
    files.update({"inputs.json": inputs.content, "account.json": account.content})
    return files, report.metrics
