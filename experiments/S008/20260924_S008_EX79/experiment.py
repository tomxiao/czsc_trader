from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from research_experiment import experiment_source_sha256


FAILED_EXPERIMENT = "20260924_S008_EX78"
FAILED_SOURCE_SHA256 = "64f5126a68aa2dc00cf2e99d41a555d655f556bac2a59a851516499608f13433"
FAILED_MANIFEST_SHA256 = "23f02aa3cf3483888cc825cb8742a65175c6281e9f1bb656c6b97b406bac755a"

failed_root = Path(__file__).resolve().parent.parent / FAILED_EXPERIMENT
if experiment_source_sha256(failed_root, ("experiment.py", "run_experiment.py")) != FAILED_SOURCE_SHA256:
    raise ValueError("EX78 frozen implementation differs")
if sha256((failed_root / "experiment_manifest.json").read_bytes()).hexdigest() != FAILED_MANIFEST_SHA256:
    raise ValueError("EX78 technical-failure manifest differs")
source = (failed_root / "experiment.py").read_text(encoding="utf-8")
identity_old = 'experiment_id="20260924_S008_EX78"'
column_old = '"negative_avoidance_ratio"'
if source.count(identity_old) != 1 or source.count(column_old) != 2:
    raise ValueError("EX78 successor patch locations differ")
source = source.replace(identity_old, 'experiment_id="20260924_S008_EX79"')
source = source.replace(column_old, '"negative_log_return_avoidance_ratio"')
exec(compile(source, str(failed_root / "experiment.py"), "exec"), globals())
