"""Content identity belongs to the public SRT runtime."""

from dataclasses import replace
import shutil
import pytest
from strategy_runtime import StrategyRuntime


@pytest.mark.parametrize(
    "change", ["relocate", "parameters", "code"], ids=["SRT-01-C07", "SRT-01-C08", "SRT-01-C09"]
)
def test_content_identity_tracks_business_bytes(runtime_candidate, tmp_path, change):
    from strategy_runtime import implementation_sha256

    original = runtime_candidate
    runtime = StrategyRuntime()
    before = runtime.identify(original, dependencies=())
    payload = {
        "runtime": dict(original.payload["runtime"]),
        "parameters": dict(original.payload["parameters"]),
    }
    if change == "relocate":
        moved = tmp_path / "relocated" / "strategy_runtime"
        shutil.copytree(original.source_root, moved)
        changed = replace(original, candidate_id="C0002", source_root=moved)
    elif change == "parameters":
        payload["parameters"] = {**dict(payload["parameters"]), "threshold": 0.8}
        changed = replace(original, payload=payload)
    else:
        moved = tmp_path / "modified" / "strategy_runtime"
        shutil.copytree(original.source_root, moved)
        descriptor = dict(payload["runtime"])
        path = moved / descriptor["source_files"][0]
        path.write_text(
            path.read_text(encoding="utf8") + "\n# distinct implementation bytes\n", encoding="utf8"
        )
        descriptor["source_sha256"] = implementation_sha256(
            tuple(descriptor["source_files"]), source_root=moved
        )
        changed = replace(original, payload={**payload, "runtime": descriptor}, source_root=moved)
    after = runtime.identify(changed, dependencies=())
    assert (after == before) is (change == "relocate")
