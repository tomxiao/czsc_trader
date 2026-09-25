from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from research_experiment import experiment_source_sha256


FAILED_EXPERIMENT = "20260925_S009_EX02"
FAILED_SOURCE_SHA256 = "38dafaf49e14bf531b5e35d010fdd6d90b9a3f279268719a88dff29c3208a940"
FAILED_MANIFEST_SHA256 = "1ca8718136c5e92aa4925281948f1862480102f7383f30e456355108a7e5c60d"

failed_root = Path(__file__).resolve().parent.parent / FAILED_EXPERIMENT
if experiment_source_sha256(failed_root, ("experiment.py", "run_experiment.py")) != FAILED_SOURCE_SHA256:
    raise ValueError("EX02 frozen implementation differs")
if sha256((failed_root / "experiment_manifest.json").read_bytes()).hexdigest() != FAILED_MANIFEST_SHA256:
    raise ValueError("EX02 technical-failure manifest differs")

source = (failed_root / "experiment.py").read_text(encoding="utf-8")
identity_old = 'identity_new = \'EXPERIMENT_ID = "20260925_S009_EX02"\''
identity_new = 'identity_new = \'EXPERIMENT_ID = "20260925_S009_EX03"\''
if source.count(identity_old) != 1:
    raise ValueError("EX02 successor identity patch location differs")
source = source.replace(identity_old, identity_new)
exec(compile(source, str(failed_root / "experiment.py"), "exec"), globals())

