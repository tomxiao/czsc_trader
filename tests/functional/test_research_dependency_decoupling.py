"""Engineering ownership and tamper tests, without changing research evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from dataflows import DataSpace


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "s007_materialize", ROOT / "research/S007/materialize_features.py",
)
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def _inputs(tmp_path, monkeypatch):
    assets = tmp_path / "data/research/S007/materialization_inputs"
    assets.mkdir(parents=True)
    source = assets / "panel.csv.gz"
    original = pd.DataFrame({
        "session": ["2026-01-06", "2026-01-05", "2026-01-05"],
        "symbol": ["A", "B", "A"], "value": [3.0, 2.0, 1.0],
    })
    original.to_csv(source, index=False)
    research = tmp_path / "research/S007"
    research.mkdir(parents=True)
    manifest = {
        "schema_version": 1, "owner": "S007", "inputs": {"panel": {
            "path": source.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "rows": 3, "date_column": "session", "start": "2026-01-05", "end": "2026-01-06",
            "historical_origin": "experiments/S005/unused.csv.gz",
        }},
    }
    manifest_file = research / "materialization_inputs.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(MODULE, "__file__", str(research / "materialize_features.py"))
    return original, source, manifest, manifest_file


def test_owned_inputs_preserve_rows_without_opening_historical_origin(tmp_path, monkeypatch):
    original, _, _, _ = _inputs(tmp_path, monkeypatch)
    loaded = MODULE.load_inputs(tmp_path, DataSpace(Path(".tmp/managed")))
    pd.testing.assert_frame_equal(loaded["panel"], original)
    assert not (tmp_path / "experiments").exists()


def test_owned_input_tampering_fails_even_after_preparation(tmp_path, monkeypatch):
    _, source, _, _ = _inputs(tmp_path, monkeypatch)
    space = DataSpace(Path(".tmp/managed"))
    MODULE.load_inputs(tmp_path, space)
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="input hash differs"):
        MODULE.load_inputs(tmp_path, space)


def test_input_manifest_cannot_rebind_to_another_batch(tmp_path, monkeypatch):
    _, _, manifest, manifest_file = _inputs(tmp_path, monkeypatch)
    manifest["inputs"]["panel"]["path"] = "experiments/S005/unused.csv.gz"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="S007-owned"):
        MODULE.load_inputs(tmp_path, DataSpace(Path(".tmp/managed")))


def test_rolling_features_use_only_the_trailing_window():
    frame = pd.DataFrame({"date": pd.date_range("2026-01-05", periods=5), "value": [1, 2, 3, 4, 5]})
    initial = MODULE.extract_rolling_features(frame, 3)
    changed = frame.copy()
    changed.loc[4, "value"] = 500
    actual = MODULE.extract_rolling_features(changed, 3)
    pd.testing.assert_frame_equal(initial.iloc[:-1], actual.iloc[:-1])
    assert initial.loc[frame.date[2], "tsfresh__value__mean__lb3"] == 2.0
    assert initial.index[0] == frame.date[2]
