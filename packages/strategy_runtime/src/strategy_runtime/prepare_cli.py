"""Prepare isolated StrategyInstance data from explicit business parameters."""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Sequence
from uuid import uuid4

from dotenv import load_dotenv

from .models import StrategyRelease, canonical_sha256
from .runtime import StrategyInit, StrategyRuntime
from .contracts import TradableWindow


def _release(value: str) -> tuple[str, str]:
    try:
        strategy_id, version = value.rsplit("-", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("release must look like S007-v1") from exc
    if not re.fullmatch(r"S\d{3,}", strategy_id) or not re.fullmatch(r"v\d+", version):
        raise argparse.ArgumentTypeError("release must look like S007-v1")
    return strategy_id, version


def _load_release(repo_root: Path, strategy_id: str, version: str) -> StrategyRelease:
    path = repo_root / "strategies" / strategy_id / "versions" / f"{version}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load frozen strategy {strategy_id}-{version}: {exc}") from exc
    release = StrategyRelease.from_mapping(payload)
    from .deployment import load_strategy_deployment
    deployment = load_strategy_deployment(repo_root / "strategies", release.release_id)
    if deployment.release_hash != release.release_hash:
        raise RuntimeError("prepared release differs from committed deployment")
    return release


def _instance_directory(
    root: Path,
    release: StrategyRelease,
    trading_date: date,
) -> Path:
    digest = sha256(
        f"{release.release_id}\0{release.release_hash}\0{trading_date.isoformat()}".encode()
    ).hexdigest()
    return root / "instances" / digest


def prepare_runtime_data(
    *,
    repo_root: Path,
    data_dir: Path,
    symbol: str,
    releases: list[tuple[str, str]],
    trading_date: date,
) -> dict[str, object]:
    """Prepare all releases, then atomically expose one PTE business-window index."""

    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = sorted(set(releases))
    if not selected:
        raise ValueError("at least one frozen strategy release is required")
    runtime = StrategyRuntime(Path(repo_root).resolve() / "strategies")
    entries: dict[str, object] = {}
    prepared_dates: set[str] = set()
    for strategy_id, version in selected:
        release = _load_release(Path(repo_root).resolve(), strategy_id, version)
        directory = _instance_directory(root, release, trading_date)
        instance = runtime.create(
            StrategyInit(
                release,
                TradableWindow(trading_date, trading_date),
                directory,
                symbol=symbol.upper(),
            )
        )
        prepared = instance.prepare_data()
        prepared_dates.add(prepared.available_through.isoformat())
        entries[release.release_id] = {
            "release_hash": release.release_hash,
            "data_dir": directory.relative_to(root).as_posix(),
            "data_identity": prepared.data_identity,
        }
    if len(prepared_dates) != 1:
        raise RuntimeError("strategy instances produced different prepared-through dates")
    index = {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "signal_date": next(iter(prepared_dates)),
        "trading_date": trading_date.isoformat(),
        "releases": entries,
    }
    index["index_sha256"] = canonical_sha256(index)
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    temporary = temporary_root / f"prepared-data-index-{uuid4().hex}.json"
    try:
        temporary.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
        os.replace(temporary, root / "prepared-data-index.json")
    finally:
        temporary.unlink(missing_ok=True)
        try:
            temporary_root.rmdir()
        except OSError:
            pass
    return index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="srt-prepare")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--release", action="append", type=_release, required=True)
    parser.add_argument("--trading-date", type=date.fromisoformat, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(Path(args.repo_root).resolve() / ".env", override=False)
    try:
        result = prepare_runtime_data(
            repo_root=args.repo_root,
            data_dir=args.data_dir,
            symbol=args.symbol,
            releases=args.release,
            trading_date=args.trading_date,
        )
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
