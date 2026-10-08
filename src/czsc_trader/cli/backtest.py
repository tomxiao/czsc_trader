"""Independent, user-requested backtests with ordinary output directories."""

from datetime import date
from hashlib import sha256
from pathlib import Path
import re
import shutil

from dataflows import Dataflows, DataSpace, ProviderConfig
from strategy_manager import StrategyVersion, StrategyManagerError
from strategy_manager.write_lock import RegistryWriteLock
from strategy_runtime import StrategyCandidate

from czsc_trader.application import BacktestRequest, CommandResult, RepositoryContext
from czsc_trader.application.backtest_service import _run_authenticated_backtest
from czsc_trader.application.errors import ExecutionError
from czsc_trader.backtesting.service import _backtest_report_files


def _independent_data(repository: RepositoryContext) -> Dataflows:
    return Dataflows(base_dir=repository.root, space=DataSpace(Path("data/backtest")),
                     providers=ProviderConfig(env_file=repository.root / ".env"))


def _save_reports(repository: RepositoryContext, output_root: Path, reference: str,
                  files: dict[str, bytes]) -> Path:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    day = date.today().strftime("%m%d")
    pattern = re.compile(rf"^{day}_([0-9]{{2,}})_")
    lock_id = sha256(str(output_root).encode("utf-8")).hexdigest()
    with RegistryWriteLock(repository.root / ".tmp/backtest-allocation" / lock_id).hold():
        numbers = [int(match[1]) for child in output_root.iterdir()
                   if child.is_dir() and (match := pattern.match(child.name)) is not None]
        destination = output_root / f"{day}_{max(numbers, default=0) + 1:02d}_{reference}"
        if destination.resolve().parent != output_root:
            raise ValueError("backtest output reference escapes output root")
        destination.mkdir()
    try:
        for name, content in files.items():
            (destination / name).write_bytes(content)
    except OSError:
        # Only this freshly allocated directory can be removed after a write failure.
        if destination.resolve().parent == output_root:
            shutil.rmtree(destination)
        raise
    return destination


def run_independent_backtest(
    repository: RepositoryContext, strategy: StrategyCandidate | StrategyVersion,
    request: BacktestRequest, output_root: Path,
) -> CommandResult:
    evaluation = _run_authenticated_backtest(repository, strategy, request, _independent_data(repository))
    reference = evaluation.snapshot.identity.reference
    try:
        files = _backtest_report_files(evaluation, content_addressed_links=False)
        destination = _save_reports(repository, output_root, reference, files)
    except (OSError, ValueError, StrategyManagerError) as exc:
        raise ExecutionError("backtest_output_failed", str(exc),
                             context={"strategy": reference, "output_root": str(output_root)}) from exc

    def location(path: Path) -> str:
        return path.relative_to(repository.root).as_posix() if path.is_relative_to(repository.root) else str(path)

    return CommandResult("PASS", "backtest.run",
                         {"strategy": reference, "output_dir": location(destination), "metrics": evaluation.metrics},
                         artifacts={name: location(destination / name) for name in files})
