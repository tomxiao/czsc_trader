"""Validated persistent configuration for the Windows service host."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PureWindowsPath

from .runtime_release import RuntimeRelease, _resolve_active_release_for_host


@dataclass(frozen=True)
class ServiceConfig:
    runtime_root: Path
    host: str = "127.0.0.1"
    port: int = 8080
    data_space: Path = Path("market")

    def __post_init__(self) -> None:
        if not self.runtime_root.is_absolute():
            raise ValueError("service runtime root must be absolute")
        if self.host != "127.0.0.1":
            raise ValueError("service HTTP host must be localhost")
        if not isinstance(self.data_space, Path):
            raise TypeError("service data_space must be a relative Path")
        windows = PureWindowsPath(str(self.data_space))
        if (not self.data_space.parts or self.data_space.is_absolute() or windows.drive
                or windows.root or ".." in self.data_space.parts or ".." in windows.parts):
            raise ValueError("service data_space must stay within shared data")

    @property
    def shared_root(self) -> Path:
        return self.runtime_root / "shared"

    def active_release(self) -> RuntimeRelease:
        return _resolve_active_release_for_host(self.runtime_root)

    def _serve_arguments(self, release: RuntimeRelease) -> list[str]:
        return [
            "serve",
            "--repo-root", str(release.release_root),
            "--database", str(self.shared_root / "state" / "runtime.db"),
            "--data-dir", str(self.shared_root / "data"),
            "--data-space", self.data_space.as_posix(),
            "--config-root", str(self.shared_root / "config"),
            "--release-manifest", str(release.manifest_path),
            "--host", self.host,
            "--port", str(self.port),
        ]

    def serve_arguments(self) -> list[str]:
        return self._serve_arguments(self.active_release())

    def pte_command(self) -> list[str]:
        release = self.active_release()
        return [str(release.pte_executable), *self._serve_arguments(release)]

    def working_directory(self) -> Path:
        return self.runtime_root

    @property
    def health_url(self) -> str:
        return f"http://{self.host}:{self.port}/api/health"

    @property
    def log_path(self) -> Path:
        return self.shared_root / "logs" / "pte.log"

    @property
    def watchdog_log_path(self) -> Path:
        return self.shared_root / "logs" / "watchdog.log"

    @property
    def config_path(self) -> Path:
        return self.shared_root / "config" / "service.json"

    def save(self, path: Path | None = None) -> Path:
        destination = path or self.config_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 3,
            "runtime_root": str(self.runtime_root),
            "host": self.host,
            "port": self.port,
            "data_space": self.data_space.as_posix(),
        }
        destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
        return destination

    @classmethod
    def load(cls, path: Path) -> "ServiceConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema_version = payload.pop("schema_version", 1)
        if schema_version == 1:
            raise ValueError(
                "repository-backed service config is no longer supported; "
                "reinstall WDG with pte-watchdog install-config --runtime-root"
            )
        if schema_version != 3:
            raise ValueError(f"unsupported service config schema: {schema_version}")
        allowed = {"runtime_root", "host", "port", "data_space"}
        if set(payload) - allowed:
            raise ValueError("service config contains unsupported fields")
        payload["runtime_root"] = Path(payload["runtime_root"])
        payload["data_space"] = Path(payload["data_space"])
        return cls(**payload)
