from __future__ import annotations

from datetime import date
from hashlib import sha256
from itertools import count
from pathlib import Path
import re

from czsc_trader.temp_workspace import replace_directory, temporary_root


def publish_run_directory(
    staging: Path,
    outputs_root: Path,
    strategy_reference: str,
    run_date: date,
) -> Path:
    """Publish MMDD_sequence_reference with one daily sequence across strategies."""
    if not isinstance(strategy_reference, str) or not re.fullmatch(
        r"S[0-9]{3}-(?:C[0-9]{4}|v[1-9][0-9]*)", strategy_reference
    ):
        raise ValueError("invalid backtest strategy reference")
    staging = Path(staging)
    outputs_root = Path(outputs_root)
    outputs_root.mkdir(parents=True, exist_ok=True)
    prefix = f"{run_date:%m%d}"
    pattern = re.compile(rf"{prefix}_([0-9]{{2,}})_S[0-9]{{3}}-(?:C[0-9]{{4}}|v[1-9][0-9]*)")

    def used_sequences() -> set[int]:
        return {
            int(match[1]) for path in outputs_root.iterdir()
            if (match := pattern.fullmatch(path.name))
        }

    # Reserve the number independently of strategy ID, including across processes.
    root_key = sha256(str(outputs_root.resolve()).casefold().encode("utf-8")).hexdigest()
    reservations = temporary_root(outputs_root) / "backtest-publication" / root_key
    reservations.mkdir(parents=True, exist_ok=True)
    for revision in count(max(used_sequences(), default=0) + 1):
        reservation = reservations / f"{prefix}_{revision:02d}"
        try:
            reservation.mkdir()
        except FileExistsError:
            continue
        try:
            # Another publisher may have completed after our initial scan.
            if revision in used_sequences():
                continue
            destination = outputs_root / f"{prefix}_{revision:02d}_{strategy_reference}"
            replace_directory(staging, destination)
            return destination.resolve()
        finally:
            reservation.rmdir()
