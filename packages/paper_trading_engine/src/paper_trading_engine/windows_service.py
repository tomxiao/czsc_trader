"""Windows SCM adapter for the minimal PTE watchdog."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import ctypes
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event
import winreg

import servicemanager
import win32event
import win32service
import win32serviceutil

from .service_config import ServiceConfig
from .runtime_release import (
    editable_installations,
    file_sha256,
    service_host_runtime_dependencies,
)
from .watchdog import Watchdog


SERVICE_NAME = "CZSC-PTE-Watchdog"
REGISTRY_PATH = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}\Parameters"


def service_failure_command() -> list[str]:
    return [
        "sc.exe", "failure", SERVICE_NAME, "reset=", "86400", "actions=",
        "restart/5000/restart/30000/restart/60000",
    ]


def prepare_service_host(servicemanager_path: Path, host_directory: Path) -> None:
    host_directory.mkdir(parents=True, exist_ok=True)
    destination = host_directory / servicemanager_path.name
    if destination.is_file() and file_sha256(destination) == file_sha256(servicemanager_path):
        return
    shutil.copy2(servicemanager_path, destination)


def find_pythonservice_executable(venv_root: Path) -> Path:
    """Locate pywin32's service host across supported Windows layouts."""
    candidates = (
        venv_root / "pythonservice.exe",
        venv_root / "Scripts" / "pythonservice.exe",
        venv_root / "Lib" / "site-packages" / "win32" / "pythonservice.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"pythonservice.exe was not found under service host: {venv_root}")


def build_bootstrap_source(venv_root: Path) -> str:
    paths = [
        venv_root / "Lib" / "site-packages",
        venv_root / "Lib" / "site-packages" / "win32",
        venv_root / "Lib" / "site-packages" / "win32" / "lib",
        venv_root / "Lib" / "site-packages" / "pywin32_system32",
    ]
    additions = "\n".join(f"sys.path.insert(0, {str(path)!r})" for path in paths)
    return (
        "import sys\n" + additions
        + "\nfrom paper_trading_engine.windows_service import PteWatchdogService\n"
    )


def _write_config_path(path: Path) -> None:
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH) as key:
        winreg.SetValueEx(key, "ConfigPath", 0, winreg.REG_SZ, str(path))
    with winreg.CreateKey(
        winreg.HKEY_LOCAL_MACHINE,
        rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}\PythonClass",
    ) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "pte_service_bootstrap.PteWatchdogService")


def _read_config_path() -> Path:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH) as key:
        return Path(winreg.QueryValueEx(key, "ConfigPath")[0])


def _service_exists() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}",
        ):
            return True
    except FileNotFoundError:
        return False


class PteWatchdogService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = "CZSC Paper Trading Watchdog"
    _svc_description_ = "Starts and monitors the CZSC paper trading engine"
    _exe_name_ = str(Path(sys.base_prefix) / "pythonservice.exe")

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = Event()
        self.stop_handle = win32event.CreateEvent(None, 0, 0, None)
        self.watchdog = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        if self.watchdog is not None:
            self.watchdog.stop_child()
        win32event.SetEvent(self.stop_handle)

    def SvcDoRun(self):
        config = ServiceConfig.load(_read_config_path())
        config.watchdog_log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            config.watchdog_log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
        logger = logging.getLogger("paper_trading_engine.service")
        try:
            self.watchdog = Watchdog(
                command=config.pte_command,
                working_directory=config.working_directory,
                health_url=config.health_url,
                log_path=config.log_path,
                sleep=self.stop_event.wait,
                logger=logger,
            )
            logger.info("watchdog service started")
            self.watchdog.run(self.stop_event)
            logger.info("watchdog service stopped")
        except Exception:
            logger.exception("service failed")
            raise


def _is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def _validate_service_host(runtime_root: Path) -> Path:
    host_releases = (runtime_root / "host" / "releases").resolve()
    actual = Path(sys.prefix).resolve()
    try:
        relative = actual.relative_to(host_releases)
    except ValueError as exc:
        raise RuntimeError(
            f"PTE watchdog must be installed from a dedicated service host: {host_releases}"
        ) from exc
    if len(relative.parts) != 2 or relative.parts[1] != ".venv":
        raise RuntimeError("PTE watchdog service host has an invalid release layout")
    site_packages = actual / "Lib" / "site-packages"
    editable = editable_installations(site_packages)
    if editable:
        raise RuntimeError(
            f"PTE watchdog service host contains editable installations: {editable}"
        )
    heavyweight = service_host_runtime_dependencies(site_packages)
    if heavyweight:
        raise RuntimeError(
            f"PTE watchdog service host contains runtime dependencies: {heavyweight}"
        )
    return actual


def main(
    argv: list[str] | None = None, *, admin_check: Callable[[], bool] = _is_admin
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "install-config":
        if not admin_check():
            sys.stderr.write("安装 CZSC-PTE-Watchdog 需要管理员权限。\n")
            return 5
        parser = argparse.ArgumentParser(prog="pte-watchdog install-config")
        parser.add_argument("--runtime-root", required=True, type=Path)
        options = parser.parse_args(arguments[1:])
        runtime_root = options.runtime_root.resolve()
        _validate_service_host(runtime_root)
        config = ServiceConfig(runtime_root=runtime_root)
        config.active_release()
        prepare_service_host(Path(servicemanager.__file__), Path(sys.exec_prefix))
        prepare_service_host(Path(servicemanager.__file__), Path(sys.base_prefix))
        virtual_host = find_pythonservice_executable(Path(sys.exec_prefix))
        base_host = Path(sys.base_prefix) / "pythonservice.exe"
        if not base_host.exists() or base_host.stat().st_size != virtual_host.stat().st_size:
            shutil.copy2(virtual_host, base_host)
        bootstrap = Path(sys.base_prefix) / "pte_service_bootstrap.py"
        bootstrap.write_text(
            build_bootstrap_source(Path(sys.exec_prefix)), encoding="utf-8", newline="\n"
        )
        path = config.save()
        action = "update" if _service_exists() else "install"
        win32serviceutil.HandleCommandLine(
            PteWatchdogService, argv=[sys.argv[0], "--startup", "auto", action]
        )
        _write_config_path(path)
        subprocess.run(service_failure_command(), check=True)
        return 0
    win32serviceutil.HandleCommandLine(PteWatchdogService, argv=[sys.argv[0], *arguments])
    return 0


if __name__ == "__main__":
    servicemanager.Initialize()
    raise SystemExit(main())
