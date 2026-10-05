"""Minimal process and HTTP watchdog for the PTE CLI runtime."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import logging
from pathlib import Path
import subprocess
import time
from typing import Protocol
from urllib.request import urlopen


class ChildProcess(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def kill(self) -> None: ...


def health_payload_is_healthy(payload: object) -> bool:
    """Require the runtime's explicit process and scheduler health assertions."""
    return bool(
        isinstance(payload, dict)
        and payload.get("runtime") == "RUNNING"
        and payload.get("watchdog_healthy") is True
    )


def http_is_healthy(url: str, timeout: float) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - validated localhost URL
            if response.status != 200:
                return False
            payload = json.loads(response.read())
        return health_payload_is_healthy(payload)
    except (OSError, ValueError, TypeError):
        return False


def spawn_pte(command: Sequence[str], cwd: Path, log_path: Path) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with log_path.open("ab") as output:
        return subprocess.Popen(
            list(command), cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
            creationflags=flags,
        )


def rotate_log(path: Path, *, max_bytes: int = 10 * 1024 * 1024, backups: int = 5) -> None:
    if not path.is_file() or path.stat().st_size < max_bytes:
        return
    for index in range(max(1, backups), 0, -1):
        source = path if index == 1 else path.with_name(f"{path.name}.{index - 1}")
        target = path.with_name(f"{path.name}.{index}")
        if source.exists():
            source.replace(target)


class Watchdog:
    def __init__(
        self,
        *,
        command: Sequence[str] | Callable[[], Sequence[str]],
        working_directory: Path | Callable[[], Path],
        health_url: str,
        log_path: Path | None = None,
        process_factory: Callable[[Sequence[str], Path, Path], ChildProcess] = spawn_pte,
        health_check: Callable[[str, float], bool] = http_is_healthy,
        sleep: Callable[[float], object] = time.sleep,
        probe_interval: float = 10.0,
        failure_threshold: int = 3,
        restart_delays: Sequence[float] = (5.0, 30.0, 60.0),
        logger: logging.Logger | None = None,
    ) -> None:
        self.command = command
        self.working_directory = working_directory
        self.health_url = health_url
        default_directory = (
            working_directory() if callable(working_directory) else working_directory
        )
        self.log_path = log_path or default_directory / "pte.log"
        self.process_factory = process_factory
        self.health_check = health_check
        self.sleep = sleep
        self.probe_interval = probe_interval
        self.failure_threshold = failure_threshold
        self.restart_delays = tuple(restart_delays)
        self.logger = logger or logging.getLogger("paper_trading_engine.watchdog")
        self.child: ChildProcess | None = None
        self.consecutive_failures = 0
        self.restart_index = 0

    def start_child(self) -> ChildProcess:
        rotate_log(self.log_path)
        command = self.command() if callable(self.command) else self.command
        working_directory = (
            self.working_directory()
            if callable(self.working_directory)
            else self.working_directory
        )
        self.child = self.process_factory(list(command), working_directory, self.log_path)
        self.logger.info("PTE child started")
        return self.child

    def stop_child(self) -> None:
        child, self.child = self.child, None
        if child is None or child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5.0)
        self.logger.info("PTE child stopped")

    def _restart_child(self, reason: str) -> None:
        self.stop_child()
        delay = self.restart_delays[min(self.restart_index, len(self.restart_delays) - 1)]
        self.restart_index += 1
        self.consecutive_failures = 0
        self.logger.warning("PTE restart in %.0f seconds: %s", delay, reason)
        interrupted = bool(self.sleep(delay))
        if not interrupted:
            self.start_child()

    def check_once(self) -> None:
        if self.child is None:
            self.start_child()
            return
        return_code = self.child.poll()
        if return_code is not None:
            if return_code == 0:
                self.child = None
                self.consecutive_failures = 0
                self.restart_index = 0
                self.logger.info("PTE requested a clean restart")
                self.start_child()
                return
            self._restart_child(f"process exited with code {return_code}")
            return
        if self.health_check(self.health_url, 3.0):
            self.consecutive_failures = 0
            self.restart_index = 0
            return
        self.consecutive_failures += 1
        self.logger.warning(
            "PTE health probe failed (%s/%s)",
            self.consecutive_failures,
            self.failure_threshold,
        )
        if self.consecutive_failures >= self.failure_threshold:
            self._restart_child("HTTP health probe failed")

    def run(self, stop_event) -> None:
        try:
            self.start_child()
            while not stop_event.wait(self.probe_interval):
                self.check_once()
        finally:
            self.stop_child()
