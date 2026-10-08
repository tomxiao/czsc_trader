"""Check full-regression OS permissions before starting expensive test lanes."""

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
import subprocess
import sys
import time


def _worker(value: str) -> str:
    return value


def preflight(run_root: Path) -> None:
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        if executor.submit(_worker, "regression-preflight").result(timeout=10) != "regression-preflight":
            raise RuntimeError("spawn worker did not return the submitted value")

    source = run_root / "permission-preflight" / "source"
    checkout = source.parent / "checkout"
    source.mkdir(parents=True)
    sample = source / "probe.txt"
    sample.write_bytes(b"regression permission preflight\n")
    command = [
        "git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
        "-c", f"core.hooksPath={source / '.disabled-hooks'}",
        "-c", "user.name=Regression Preflight",
        "-c", "user.email=preflight@example.invalid",
    ]
    for arguments in (
        ["init", "--quiet"], ["add", "probe.txt"],
        ["commit", "--quiet", "-m", "permission preflight"],
        ["clone", "--quiet", "--no-hardlinks", str(source), str(checkout)],
    ):
        subprocess.run(
            command + arguments, cwd=source, check=True, timeout=10,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    if (checkout / "probe.txt").read_bytes() != sample.read_bytes():
        raise RuntimeError("local Git clone changed probe content")


if __name__ == "__main__":
    started = time.monotonic()
    try:
        preflight(Path(sys.argv[1]).resolve())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        detail = exc.stderr.decode(errors="replace") if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"REGRESSION_PREFLIGHT=FAIL {type(exc).__name__}: {detail}")
        sys.exit(2)
    print(f"REGRESSION_PREFLIGHT=PASS SECONDS={time.monotonic() - started:.2f}")
