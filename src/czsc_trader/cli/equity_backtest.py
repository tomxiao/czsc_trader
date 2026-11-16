"""Replay a verified frozen V5 account against an explicit DFLS preparation."""

from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from uuid import UUID

from dataflows import Dataflows, DataSpace, MarketId, PreparedDataRef, ProviderConfig, SourceRef, TimeInterval
from dataflows.asset_store import StoreError
from dataflows.equity_data import sessions_from_metadata
from strategy_manager import StrategyVersion
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, ExecutionPriceBasis, StepDataWindow
from strategy_runtime.data_preparation import prepare_observations
from strategy_runtime.deployment import validate_release_package
from strategy_runtime.errors import StrategyRuntimeError

from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.errors import ExecutionError, ValidationError
from czsc_trader.research_tools.equity_evaluation import (
    EquityArtifact, EquitySources, equity_product_requests, fetch_equity_products, _records,
)
from czsc_trader.research_tools.equity_replay import (
    _AccountOutputContext, _ReplayAccountRequest, _bytes, _compute_account, _read,
)


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
    prepared: PreparedDataRef
    history_start: date
    fee_rate: float
    sources: EquitySources
    step_data_windows: tuple[StepDataWindow, ...]

    def __post_init__(self):
        if not self.history_start <= self.start <= self.end:
            raise ValueError("V5 history_start, start and end must be ordered")
        if not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        if type(self.fee_rate) not in (int, float) or not isfinite(self.fee_rate) or not 0 <= self.fee_rate < 1:
            raise ValueError("fee_rate must be finite and in [0, 1)")
        if self.price_basis is not ExecutionPriceBasis.HFQ_RESEARCH:
            raise ValueError("V5 historical accounts require HFQ_RESEARCH")
        names = [window.name for window in self.step_data_windows]
        if len(names) != len(set(names)) or any(window.end > self.end for window in self.step_data_windows):
            raise ValueError("V5 step windows must have distinct names and end within the backtest")

    @classmethod
    def from_file(cls, path: Path, *, symbol: str, asset_type: str, start: date, end: date,
                  initial_cash: float, lot_size: int, price_basis: ExecutionPriceBasis) -> "EquityBacktestRequest":
        try:
            value = _read(path.read_bytes())
            fields = {"data_space", "prepared", "history_start", "fee_rate", "sources", "step_data_windows"}
            if type(value) is not dict or set(value) != fields:
                raise ValueError("V5 equity inputs require: " + ", ".join(sorted(fields)))
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
                       DataSpace(Path(value["data_space"])), reference, date.fromisoformat(value["history_start"]),
                       value["fee_rate"], sources, tuple(StepDataWindow.from_dict(window) for window in windows))
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

    candidate = EquityStrategyCandidate(strategy.strategy_id, package.runtime_candidate_id, definition, package.source_root)
    try:
        space_root = (repository.root / request.space.path).resolve()
        if not space_root.is_relative_to(repository.root) or not (space_root / "assets.sqlite3").is_file():
            raise ValueError("data_space must locate an existing DFLS space inside the repository")
        flows = Dataflows(base_dir=repository.root, space=request.space, providers=ProviderConfig(bindings={}))
        items = equity_product_requests(definition, request.sources, request.history_start, request.start, request.end,
                                        specification=spec)
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
        metrics = _read(account.content)["run"]["metrics"]
    except (OSError, RuntimeError, StoreError, StrategyRuntimeError, ValueError) as exc:
        raise ExecutionError("backtest_failed", str(exc), context={"strategy": reference}) from exc

    manifest = {"schema": "tdr-frozen-backtest/v5", "strategy": reference,
        "release_hash": strategy.release_hash, "package_sha256": package.package_sha256,
        "instrument": asdict(instrument), "window": asdict(window), "history_start": request.history_start,
        "requested_dates": {"start": request.start, "end": request.end},
        "execution_spec": definition.to_dict()["execution_spec"], "price_basis": "HFQ",
        "quantity_basis": "SIMULATED_INTEGER_UNITS", "initial_cash": request.initial_cash,
        "fee_rate": request.fee_rate, "sources": asdict(request.sources), "data_space": request.space.path.as_posix(),
        "prepared": {key: str(value) for key, value in asdict(request.prepared).items()},
        "step_data_windows": [item.to_dict() for item in request.step_data_windows],
        "artifacts": {"inputs.json": inputs.reference(), "account.json": account.reference()}}
    report = (
        f"# {reference} 回测\n\n{instrument.symbol} · {request.start} 至 {request.end}\n\n"
        "| 指标 | 结果 |\n| --- | --- |\n"
        f"| 累计收益 | {metrics['total_return']:.2%} |\n"
        f"| 日末最大回撤 | {metrics['daily_max_drawdown']:.2%} |\n"
        f"| 交易日 | {metrics['sessions']} |\n| 闭合交易 | {metrics['closed_cycles']} |\n\n"
        "[完整指标](metrics.json) · [账户与 DFLS 取数凭证](account.json) · [输入身份](manifest.json)\n"
    )
    return {"manifest.json": _bytes(manifest), "inputs.json": inputs.content, "account.json": account.content,
            "metrics.json": _bytes(metrics), "report.md": report.encode("utf-8")}, metrics
