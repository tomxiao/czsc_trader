"""Configuration owned and parsed by the selected PTE runtime."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from dataflows import DataSpace


@dataclass(frozen=True, slots=True)
class PteRuntimeConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    data_space: Path = Path("market")

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("PTE HTTP host must be localhost")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise TypeError("PTE HTTP port must be an integer")
        if not 1 <= self.port <= 65535:
            raise ValueError("PTE HTTP port must be between 1 and 65535")
        DataSpace(self.data_space)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1,
            "host": self.host,
            "port": self.port,
            "data_space": self.data_space.as_posix(),
        }, indent=2) + "\n", encoding="utf-8", newline="\n")
        return path

    @classmethod
    def load(cls, path: Path) -> "PteRuntimeConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("PTE runtime config must be an object")
        schema = payload.get("schema_version")
        if type(schema) is not int or schema != 1:
            raise ValueError(f"unsupported PTE runtime config schema: {schema}")
        if set(payload) != {"schema_version", "host", "port", "data_space"}:
            raise ValueError("PTE runtime config contains missing or unsupported fields")
        if not isinstance(payload["data_space"], str):
            raise TypeError("PTE runtime data_space must be a relative path string")
        return cls(host=payload["host"], port=payload["port"],
                   data_space=Path(payload["data_space"]))
