"""Watchdog-owned configuration and the stable PTE process-launch contract."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from .runtime_release import file_sha256


@dataclass(frozen=True)
class ServiceConfig:
    runtime_root: Path
    health_url: str = "http://127.0.0.1:8080/api/health"

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_root, Path) or not self.runtime_root.is_absolute():
            raise ValueError("service runtime root must be an absolute Path")
        if not isinstance(self.health_url, str):
            raise ValueError("watchdog health URL must be a localhost HTTP endpoint")
        parsed = urlsplit(self.health_url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path != "/api/health"
                or parsed.port is None or not 1 <= parsed.port <= 65535):
            raise ValueError("watchdog health URL must be a localhost HTTP endpoint")

    @property
    def shared_root(self) -> Path:
        return self.runtime_root / "shared"

    def pte_command(self) -> list[str]:
        """Resolve each launch without parsing the target PTE's configuration.

        WDG authenticates the selection envelope. The selected PTE validates its
        own manifest, strategies and runtime settings inside its interpreter.
        """
        active = json.loads((self.shared_root / "config" / "active-release.json").read_text(encoding="utf-8"))
        if not isinstance(active, dict) or type(active.get("schema_version")) is not int or active["schema_version"] != 1:
            raise ValueError("unsupported active PTE release schema")
        release_id = active.get("release_id")
        if not isinstance(release_id, str) or re.fullmatch(r"v[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?", release_id) is None:
            raise ValueError("invalid active PTE release id")
        releases = (self.runtime_root / "releases").resolve()
        release = (releases / release_id).resolve()
        if release.parent != releases:
            raise ValueError("active PTE release escapes releases root")
        manifest = (release / "release-manifest.json").resolve()
        if manifest.parent != release or file_sha256(manifest) != active.get("manifest_sha256"):
            raise ValueError("active PTE release manifest identity differs")
        scripts = release / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
        executable = (scripts / ("pte.exe" if sys.platform == "win32" else "pte")).resolve()
        if not executable.is_relative_to(release) or not executable.is_file():
            raise ValueError("active PTE launch executable is unavailable or escapes release")
        return [str(executable), "serve-runtime", "--runtime-root", str(self.runtime_root)]

    def working_directory(self) -> Path:
        return self.runtime_root

    @property
    def log_path(self) -> Path:
        return self.shared_root / "logs" / "pte.log"

    @property
    def watchdog_log_path(self) -> Path:
        return self.shared_root / "logs" / "watchdog.log"

    @property
    def config_path(self) -> Path:
        return self.shared_root / "config" / "watchdog.json"

    def save(self, path: Path | None = None) -> Path:
        destination = path or self.config_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "runtime_root": str(self.runtime_root), "health_url": self.health_url}
        destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
        return destination

    @classmethod
    def load(cls, path: Path) -> "ServiceConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "runtime_root", "health_url"}:
            raise ValueError("watchdog configuration fields are invalid")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ValueError("unsupported watchdog configuration schema")
        return cls(runtime_root=Path(payload["runtime_root"]), health_url=payload["health_url"])
